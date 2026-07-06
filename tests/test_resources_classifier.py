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
