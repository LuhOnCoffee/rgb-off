from __future__ import annotations

import pytest

from rgboff import vendors


@pytest.mark.parametrize("display_name,expected", [
    ("Armoury Crate", "ASUS Armoury Crate"),
    ("iCUE 5 Software", "Corsair iCUE"),
    ("MSI Mystic Light", "MSI Mystic Light"),
    ("RGB Fusion 2.0", "Gigabyte RGB Fusion"),
    ("ASRock Polychrome RGB", "ASRock Polychrome RGB"),
    ("NZXT CAM", "NZXT CAM"),
    ("Razer Synapse 3", "Razer Synapse / Chroma"),
    ("Kingston FURY CTRL", "Kingston FURY CTRL"),
    ("AURA Lighting Effect Service", "ASUS Aura / Lighting Control"),
    ("Logitech G HUB", "Logitech G HUB / Gaming Software"),
])
def test_catalog_matches(display_name, expected):
    entry = vendors.match_catalog(display_name)
    assert entry is not None and entry.name == expected


@pytest.mark.parametrize("display_name", [
    "Microsoft Edge",
    "NVIDIA Graphics Driver 555.99",
    "Python 3.12.4 (64-bit)",
    "7-Zip 24.07",
])
def test_catalog_ignores_unrelated_software(display_name):
    assert vendors.match_catalog(display_name) is None


def test_catalog_has_no_duplicate_names():
    names = [e.name for e in vendors.CATALOG]
    assert len(names) == len(set(names))


def test_cooling_apps_all_explain_themselves():
    for entry in vendors.CATALOG:
        if entry.cooling:
            assert entry.note.strip(), f"{entry.name} needs a note"


@pytest.mark.parametrize("command,expected", [
    ('"C:\\Program Files\\App\\unins000.exe"', ("C:\\Program Files\\App\\unins000.exe", "")),
    ('"C:\\App\\x.exe" --uninstall --quiet', ("C:\\App\\x.exe", "--uninstall --quiet")),
    ("C:\\Apps\\setup.exe -remove", ("C:\\Apps\\setup.exe", "-remove")),
    ("C:\\Apps\\Uninstall.exe", ("C:\\Apps\\Uninstall.exe", "")),
])
def test_split_command(command, expected):
    assert vendors.split_command(command) == expected


def _app(uninstall="", quiet="", product_code="Key") -> vendors.InstalledApp:
    return vendors.InstalledApp(
        display_name="Test", version="1.0", publisher="Test",
        uninstall_string=uninstall, quiet_uninstall=quiet,
        product_code=product_code, entry=vendors.CATALOG[0],
    )


def test_quiet_string_wins():
    plan = vendors.plan_uninstall(_app(quiet='"C:\\x.exe" /S /norestart'))
    assert plan.silent and plan.executable == "C:\\x.exe"
    assert plan.args == ["/S", "/norestart"]


def test_msi_product_code_becomes_msiexec():
    guid = "{1D2E3F4A-5B6C-7D8E-9F0A-1B2C3D4E5F60}"
    plan = vendors.plan_uninstall(_app(uninstall="MsiExec.exe /I" + guid,
                                       product_code=guid))
    assert plan.silent
    assert plan.executable.lower().endswith("msiexec.exe")
    assert plan.args == ["/x", guid, "/qn", "/norestart"]


def test_inno_setup_gets_verysilent():
    plan = vendors.plan_uninstall(_app(uninstall='"C:\\App\\unins000.exe"'))
    assert plan.silent and "/VERYSILENT" in plan.args


def test_nsis_gets_capital_s():
    plan = vendors.plan_uninstall(_app(uninstall="C:\\App\\Uninstall.exe"))
    assert plan.silent and plan.args == ["/S"]


def test_unknown_installer_runs_visibly_rather_than_guessing():
    """Guessing switches on an unknown installer risks running something that
    is not an uninstall at all."""
    plan = vendors.plan_uninstall(_app(uninstall="C:\\App\\setup.exe -remove"))
    assert plan.usable and not plan.silent


def test_missing_uninstall_string_is_unusable():
    assert not vendors.plan_uninstall(_app()).usable


@pytest.mark.skipif(vendors.IS_WINDOWS,
                    reason="on Windows this reads the real uninstall registry")
def test_scan_returns_empty_without_a_registry():
    assert vendors.scan_installed() == []


def test_scan_returns_well_formed_results():
    """Runs everywhere. On a developer's own Windows box this really does walk
    the registry and will find whatever vendor software is installed - so it
    checks the shape of the result, not its contents."""
    result = vendors.scan_installed()
    assert isinstance(result, list)
    for app in result:
        assert isinstance(app, vendors.InstalledApp)
        assert app.display_name.strip()
        assert app.entry in vendors.CATALOG
        assert isinstance(app.cooling, bool)
        # Every match must yield a plan we can reason about, even an unusable one.
        vendors.plan_uninstall(app)


def test_scan_sorts_lighting_only_apps_first():
    apps = vendors.scan_installed()
    cooling_flags = [a.cooling for a in apps]
    assert cooling_flags == sorted(cooling_flags)
