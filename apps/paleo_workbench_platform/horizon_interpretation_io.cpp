#include "horizon_interpretation_io.hpp"

#include <pwb/interchange/zip_archive.hpp>
#include <QSaveFile>
#include <QTemporaryFile>
#include <QFile>
#include <bit>
#include <cstring>
#include <limits>
#include <regex>
#include <stdexcept>

namespace pwb::app::joint_analysis {
namespace {
struct Npy {
    std::string dtype;
    std::vector<std::size_t> shape;
    std::string bytes;
};
Npy decode_npy(const std::string& bytes) {
    if (bytes.size() < 10 || bytes.compare(0, 6, "\x93NUMPY", 6) != 0)
        throw std::runtime_error("invalid interpretation NPY header");
    const auto major = static_cast<unsigned char>(bytes[6]);
    const std::size_t prefix = major == 1 ? 10 : 12;
    if ((major != 1 && major != 2 && major != 3) || bytes.size() < prefix)
        throw std::runtime_error("unsupported interpretation NPY version");
    std::size_t length = 0;
    for (std::size_t i = 8; i < prefix; ++i)
        length |= static_cast<std::size_t>(static_cast<unsigned char>(bytes[i])) << (8 * (i - 8));
    if (length > bytes.size() - prefix)
        throw std::runtime_error("truncated interpretation NPY header");
    const std::string header = bytes.substr(prefix, length);
    std::smatch m;
    if (!std::regex_search(header, m, std::regex("['\"]descr['\"]\\s*:\\s*['\"]([^'\"]+)['\"]")))
        throw std::runtime_error("missing interpretation dtype");
    Npy out;
    out.dtype = m[1];
    if (!std::regex_search(header, std::regex("['\"]fortran_order['\"]\\s*:\\s*False")))
        throw std::runtime_error("interpretation must use C-order arrays");
    if (!std::regex_search(header, m, std::regex("['\"]shape['\"]\\s*:\\s*\\(([^)]*)\\)")))
        throw std::runtime_error("missing interpretation shape");
    const std::string dimensions = m[1];
    const std::regex number("[0-9]+");
    for (auto it = std::sregex_iterator(dimensions.begin(), dimensions.end(), number);
         it != std::sregex_iterator(); ++it)
        out.shape.push_back(static_cast<std::size_t>(std::stoull(it->str())));
    out.bytes = bytes.substr(prefix + length);
    return out;
}
std::string encode_npy(const std::string& dtype, const std::string& shape,
                       const std::string& payload) {
    std::string header = "{'descr': '" + dtype + "', 'fortran_order': False, 'shape': (" + shape + "), }";
    header.append((64 - ((10 + header.size() + 1) % 64)) % 64, ' ');
    header += '\n';
    std::string out("\x93NUMPY\x01\x00", 8);
    out.push_back(static_cast<char>(header.size() & 255));
    out.push_back(static_cast<char>((header.size() >> 8) & 255));
    return out + header + payload;
}
std::string read_array(const pwb::interchange::ZipReader& archive, const char* name) {
    const auto* entry = archive.find(name);
    if (!entry || entry->size > 512ull * 1024 * 1024)
        throw std::runtime_error(std::string("missing/oversized interpretation array: ") + name);
    return archive.read_entry_bytes(*entry);
}
}
HorizonInterpretation read_horizon_interpretation(const std::filesystem::path& path) {
    pwb::interchange::ZipReader archive(path);
    const auto z = decode_npy(read_array(archive, "z.npy"));
    if (z.shape.size() != 2 || z.shape[0] == 0 || z.shape[1] == 0 ||
        z.shape[0] > std::numeric_limits<std::size_t>::max() / z.shape[1] ||
        (z.dtype != "<f4" && z.dtype != ">f4" && z.dtype != "=f4"))
        throw std::runtime_error("interpretation z must be a non-empty float32 matrix");
    const std::size_t count = z.shape[0] * z.shape[1];
    if (count > z.bytes.size() / 4 || z.bytes.size() != count * 4)
        throw std::runtime_error("interpretation z shape/payload mismatch");
    HorizonInterpretation out;
    out.z.rows = z.shape[0]; out.z.cols = z.shape[1]; out.z.data.resize(count);
    for (std::size_t k = 0; k < count; ++k) {
        std::uint32_t bits = 0;
        const bool big = z.dtype == ">f4" || (z.dtype == "=f4" && std::endian::native == std::endian::big);
        for (std::size_t b = 0; b < 4; ++b)
            bits |= static_cast<std::uint32_t>(static_cast<unsigned char>(z.bytes[4*k+b])) << (8 * (big ? 3-b : b));
        out.z.data[k] = std::bit_cast<float>(bits);
    }
    out.descriptor = pwb::domain::Json::object();
    if (archive.find("__descriptor__.npy")) {
        const auto desc = decode_npy(read_array(archive, "__descriptor__.npy"));
        if (desc.dtype != "|u1" || desc.shape.size() != 1 || desc.shape[0] != desc.bytes.size())
            throw std::runtime_error("invalid interpretation descriptor array");
        out.descriptor = pwb::domain::Json::parse(desc.bytes);
        if (!out.descriptor.is_object() || out.descriptor.value("artifact_version", 1) != 1)
            throw std::runtime_error("unsupported interpretation descriptor");
    }
    return out;
}
void write_horizon_interpretation(const std::filesystem::path& path,
                                  const HorizonInterpretation& artifact) {
    const auto& z = artifact.z;
    if (z.rows == 0 || z.cols == 0 || z.rows > std::numeric_limits<std::size_t>::max() / z.cols ||
        z.data.size() != z.rows*z.cols)
        throw std::runtime_error("invalid interpretation grid shape");
    std::string payload;
    payload.reserve(z.data.size()*4);
    for (double v : z.data) {
        const auto bits = std::bit_cast<std::uint32_t>(static_cast<float>(v));
        for (int b = 0; b < 4; ++b) payload.push_back(static_cast<char>((bits >> (8*b)) & 255));
    }
    auto desc = artifact.descriptor;
    desc["artifact_version"] = 1;
    desc["shape"] = {z.rows, z.cols};
    const std::string json = desc.dump();
    const auto u8 = path.u8string();
    const QString target = QString::fromUtf8(reinterpret_cast<const char*>(u8.data()), static_cast<int>(u8.size()));
    QTemporaryFile temp(target + QStringLiteral(".XXXXXX"));
    if (!temp.open()) throw std::runtime_error("cannot stage interpretation artifact");
    const QString stage = temp.fileName();
    temp.close();
    {
        pwb::interchange::ZipWriter writer(std::filesystem::u8path(stage.toUtf8().constData()));
        writer.add_bytes("z.npy", encode_npy("<f4", std::to_string(z.rows) + ", " + std::to_string(z.cols), payload));
        writer.add_bytes("__descriptor__.npy", encode_npy("|u1", std::to_string(json.size()) + ",", json));
        writer.finish();
    }
    QFile source(stage);
    QSaveFile dest(target);
    if (!source.open(QIODevice::ReadOnly) || !dest.open(QIODevice::WriteOnly))
        throw std::runtime_error("cannot publish interpretation artifact");
    while (!source.atEnd()) {
        const auto chunk = source.read(1024*1024);
        if (chunk.isEmpty() || dest.write(chunk) != chunk.size())
            throw std::runtime_error("cannot write interpretation artifact");
    }
    if (!dest.commit()) throw std::runtime_error("cannot commit interpretation artifact");
}
}
