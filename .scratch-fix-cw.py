import io
p = 'libs/visualization/src/cross_well/cross_well_tests/cross_well_oracle_test.cpp'
s = io.open(p, encoding='utf-8', errors='surrogateescape').read()
old = '''        auto base = std::filesystem::temp_directory_path();
        char pattern[128];
        std::snprintf(pattern, sizeof(pattern), "viz_b_test_XXXXXX");
        std::string dir = (base / "viz_b_test_").string();
        std::vector<char> tmpl(dir.begin(), dir.end());
        tmpl.push_back('\0');
        char* made = mkdtemp(tmpl.data());
        path_ = made != nullptr ? made : (base / "viz_b_test_fallback");
        std::filesystem::create_directories(path_);'''
new = '''        auto base = std::filesystem::temp_directory_path();
        // PWB-V14-DATA-LINEAGE: mkdtemp is POSIX-only; same contract (a
        // fresh unique created directory) via the temp root + probe loop.
        static unsigned seq = 0;
        std::error_code ec;
        for (unsigned attempt = 0; attempt < 4096; ++attempt) {
            const std::filesystem::path candidate =
                base / ("viz_b_test_" + std::to_string(pwb_test_pid()) +
                        "_" + std::to_string(seq++));
            if (std::filesystem::create_directory(candidate, ec)) {
                path_ = candidate;
                break;
            }
        }
        if (path_.empty()) path_ = base / "viz_b_test_fallback";
        std::filesystem::create_directories(path_);'''
assert old in s, 'anchor'
s = s.replace(old, new, 1)
s = s.replace('''#include <unistd.h>''', '''#if defined(_WIN32)
#include <process.h>
inline int pwb_test_pid() { return _getpid(); }
#else
#include <unistd.h>
inline int pwb_test_pid() { return static_cast<int>(::getpid()); }
#endif''')
io.open(p, 'w', encoding='utf-8', errors='surrogateescape', newline='').write(s)
print('cross_well mkdtemp patched')
