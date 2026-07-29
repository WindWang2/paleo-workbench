#pragma once

#include <cstdint>
#include <functional>
#include <string>
#include <string_view>

#include <welllog/core/document.hpp>
#include <welllog/core/result.hpp>
#include <welllog/io/export.hpp>

namespace welllog {

inline constexpr std::uint32_t manifest_schema_version = 1;
inline constexpr std::string_view welllog_sdk_version = "0.1.0";
inline constexpr std::string_view manifest_sdk_requirement = ">=0.1.0 <1.0.0";

struct BufferDescriptor {
  BufferSourceReference source;
  std::uint64_t length{};
  std::uint64_t stride_bytes{};
  ScalarType scalar_type{ScalarType::float64};
  std::uint64_t byte_capacity{};
};

struct NullBitmapDescriptor {
  BufferSourceReference source;
  std::uint64_t bit_length{};
  std::uint64_t byte_capacity{};
};

struct ManifestResolvers {
  std::function<Result<BufferView>(const BufferDescriptor &)> buffer;
  std::function<Result<NullBitmapView>(const NullBitmapDescriptor &)>
      null_bitmap;
};

class WELLLOG_IO_API ManifestText {
public:
  ManifestText();
  ~ManifestText();
  ManifestText(const ManifestText &);
  ManifestText &operator=(const ManifestText &);
  ManifestText(ManifestText &&) noexcept;
  ManifestText &operator=(ManifestText &&) noexcept;

  [[nodiscard]] std::string_view text() const noexcept;

private:
  struct Impl;
  explicit ManifestText(std::string text);
  std::shared_ptr<const Impl> impl_;
  friend class ManifestCodec;
};

class WELLLOG_IO_API ManifestCodec {
public:
  [[nodiscard]] static Result<ManifestText>
  write(const WellLogDocument &document);
  [[nodiscard]] static Result<WellLogDocument>
  read(std::string_view manifest, const ManifestResolvers &resolvers);
};

} // namespace welllog
