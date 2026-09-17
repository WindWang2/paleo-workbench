#include <pwb/application/adapters/volume_payload.hpp>

#include <cstring>
#include <fstream>

namespace pwb::application {
namespace {

constexpr char kMagic[8] = {'P', 'W', 'B', 'V', 'O', 'L', '1', '\0'};
static_assert(sizeof(float) == 4, "float32 payload requires 32-bit float");

void put_u32(std::vector<char>& buffer, std::uint32_t value) {
    for (int i = 0; i < 4; ++i) {
        buffer.push_back(static_cast<char>((value >> (8 * i)) & 0xFF));
    }
}

bool get_u32(const char* data, std::uint32_t* out) {
    std::uint32_t value = 0;
    for (int i = 0; i < 4; ++i) {
        value |= static_cast<std::uint32_t>(
                     static_cast<unsigned char>(data[i])) << (8 * i);
    }
    *out = value;
    return true;
}

pwb::domain::Json header_to_json(const VolumePayloadHeader& h) {
    pwb::domain::Json json = pwb::domain::Json::object();
    json["version"] = 1;
    json["shape"] = {h.ni, h.nc, h.ns};
    json["axes"] = {"inline", "crossline", "sample"};
    json["axis_starts"] = {h.inline_start, h.crossline_start, h.sample_start};
    json["axis_steps"] = {h.inline_step, h.crossline_step, h.sample_step};
    json["axis_units"] = {h.inline_unit, h.crossline_unit, h.sample_unit};
    json["value_unit"] = h.value_unit;
    json["layout"] = "c-order-f32";
    json["algorithm_id"] = h.algorithm_id;
    json["algorithm_version"] = h.algorithm_version;
    json["build_identity"] = h.build_identity;
    json["request_id"] = h.request_id;
    json["approximations"] = h.approximations;
    return json;
}

}  // namespace

std::string write_volume_payload(const VolumePayload& payload,
                                 const std::filesystem::path& path) {
    const VolumePayloadHeader& h = payload.header;
    const std::uint64_t expected =
        static_cast<std::uint64_t>(h.ni) * h.nc * h.ns;
    if (payload.samples.size() != expected) {
        return "payload size mismatch: header says " +
            std::to_string(expected) + " samples, vector has " +
            std::to_string(payload.samples.size());
    }
    const pwb::domain::Json header_json = header_to_json(h);
    const std::string header_text = header_json.dump();

    std::vector<char> buffer;
    buffer.reserve(sizeof(kMagic) + 4 + header_text.size() +
                   payload.samples.size() * 4);
    buffer.insert(buffer.end(), kMagic, kMagic + sizeof(kMagic));
    put_u32(buffer, static_cast<std::uint32_t>(header_text.size()));
    buffer.insert(buffer.end(), header_text.begin(), header_text.end());
    const char* raw = reinterpret_cast<const char*>(payload.samples.data());
    buffer.insert(buffer.end(), raw,
                  raw + payload.samples.size() * sizeof(float));

    std::ofstream file(path, std::ios::binary | std::ios::trunc);
    if (!file.is_open()) return "cannot open output file: " + path.string();
    file.write(buffer.data(), static_cast<std::streamsize>(buffer.size()));
    if (!file.good()) return "write failed: " + path.string();
    return "";
}

std::string read_volume_payload(const std::filesystem::path& path,
                                VolumePayload* out) {
    std::ifstream file(path, std::ios::binary);
    if (!file.is_open()) return "cannot open payload: " + path.string();

    char magic[sizeof(kMagic)] = {};
    file.read(magic, sizeof(magic));
    if (!file.good() || std::memcmp(magic, kMagic, sizeof(kMagic)) != 0) {
        return "bad magic (not a PWBVOL1 file): " + path.string();
    }
    char size_bytes[4] = {};
    file.read(size_bytes, 4);
    if (!file.good()) return "truncated header size";
    std::uint32_t header_size = 0;
    get_u32(size_bytes, &header_size);
    if (header_size == 0 || header_size > (16u << 20)) {
        return "implausible header size: " + std::to_string(header_size);
    }
    std::string header_text(header_size, '\0');
    file.read(header_text.data(), header_size);
    if (!file.good()) return "truncated header body";

    pwb::domain::Json header_json = pwb::domain::Json::parse(
        header_text, nullptr, false);
    if (header_json.is_discarded()) return "header JSON invalid";
    if (!header_json.contains("version") ||
        header_json["version"].get<int>() != 1) {
        return "unsupported payload version";
    }

    VolumePayload loaded;
    VolumePayloadHeader& h = loaded.header;
    const auto shape = header_json.at("shape");
    if (!shape.is_array() || shape.size() != 3) return "bad shape";
    h.ni = shape.at(0).get<std::uint32_t>();
    h.nc = shape.at(1).get<std::uint32_t>();
    h.ns = shape.at(2).get<std::uint32_t>();
    const auto starts = header_json.at("axis_starts");
    h.inline_start = starts.at(0).get<double>();
    h.crossline_start = starts.at(1).get<double>();
    h.sample_start = starts.at(2).get<double>();
    const auto steps = header_json.at("axis_steps");
    h.inline_step = steps.at(0).get<double>();
    h.crossline_step = steps.at(1).get<double>();
    h.sample_step = steps.at(2).get<double>();
    const auto units = header_json.at("axis_units");
    h.inline_unit = units.at(0).get<std::string>();
    h.crossline_unit = units.at(1).get<std::string>();
    h.sample_unit = units.at(2).get<std::string>();
    h.value_unit = header_json.at("value_unit").get<std::string>();
    h.algorithm_id = header_json.value("algorithm_id", std::string());
    h.algorithm_version = header_json.value("algorithm_version", std::string());
    h.build_identity = header_json.value("build_identity", std::string());
    h.request_id = header_json.value("request_id", std::string());
    if (header_json.contains("approximations") &&
        header_json["approximations"].is_array()) {
        h.approximations =
            header_json["approximations"].get<std::vector<std::string>>();
    }

    const std::uint64_t count =
        static_cast<std::uint64_t>(h.ni) * h.nc * h.ns;
    loaded.samples.resize(static_cast<size_t>(count));
    file.read(reinterpret_cast<char*>(loaded.samples.data()),
              static_cast<std::streamsize>(count * sizeof(float)));
    if (!file.good()) return "truncated payload body";
    file.get();
    if (!file.eof()) return "trailing bytes after payload";

    *out = std::move(loaded);
    return "";
}

}  // namespace pwb::application
