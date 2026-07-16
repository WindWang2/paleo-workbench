from pathlib import Path

from paleo_workbench.resources.classifier import classify_path


def test_classifies_core_data_formats():
    assert classify_path(Path("well_a.las")) == ("well_log", "las", "indexed")
    assert classify_path(Path("line_01.sgy")) == ("seismic", "sgy", "indexed")
    assert classify_path(Path("horizon.segy")) == ("seismic", "segy", "indexed")


def test_classifies_dat_variants_from_folder_names():
    assert classify_path(Path("td/table.dat")) == ("time_depth", "dat", "indexed")
    assert classify_path(Path("层位/top.dat")) == ("horizon", "dat", "indexed")
    assert classify_path(Path("井分层/well.dat")) == (
        "well_stratification",
        "dat",
        "indexed",
    )


def test_well_head_dat_under_well_folder():
    assert classify_path(Path("井位/ExportWellHead.dat")) == (
        "well_head",
        "dat",
        "indexed",
    )


def test_classifies_reference_and_unknown_formats():
    assert classify_path(Path("report.pdf")) == (
        "document",
        "pdf",
        "indexed_reference",
    )
    assert classify_path(Path("image.tif")) == (
        "image_reference",
        "tif",
        "indexed_reference",
    )
    assert classify_path(Path("相图_reference.dfb")) == (
        "reference_map",
        "dfb",
        "indexed_reference",
    )
    assert classify_path(Path("notes.xyz")) == (
        "unknown",
        "xyz",
        "indexed_reference",
    )


def test_markdown_classified_as_document():
    rtype, fmt, _ = classify_path(Path("notes.md"))
    assert rtype == "document"
    assert fmt == "md"


def test_html_classified_as_document():
    rtype, fmt, _ = classify_path(Path("report.html"))
    assert rtype == "document"
    assert fmt == "html"


def test_json_classified_as_tabular_or_geojson():
    rtype, fmt, _ = classify_path(Path("config.json"))
    assert rtype == "tabular"
    assert fmt == "json"
    rtype2, fmt2, _ = classify_path(Path("facies.geojson"))
    assert rtype2 == "geojson"
    assert fmt2 == "geojson"


def test_audio_classified_as_unknown():
    rtype, fmt, _ = classify_path(Path("clip.wav"))
    assert rtype == "unknown"
    assert fmt == "wav"


def test_zip_is_classified_from_its_extension_without_content_guessing():
    assert classify_path(Path("bundle.zip")) == (
        "archive",
        "zip",
        "indexed_reference",
    )
    assert classify_path(Path("looks-like-zip.bin")) == (
        "unknown",
        "bin",
        "indexed_reference",
    )
