from pathlib import Path


def test_static_profile_keeps_status_and_source_lineage_visible() -> None:
    path = Path(__file__).resolve().parents[1] / "prototypes" / "organization-profile.html"
    page = path.read_text(encoding="utf-8")

    assert "unverified match" in page
    assert "This identity link has not been verified" in page
    assert "data.austintexas.gov/resource/3kfv-biw6.json" in page
    assert "data.austintexas.gov/resource/8c6z-qnmj.json" in page
    assert "365d9e3f5c32aa627849ceae36c58a50bb22e539e31158bcfcd97e1ffec3d01f" in page
    assert "a4b9ec9541bb2a36fd433bedc61d83636a23f739c112326743c959e99f0dc23a" in page
    assert "Not for publication" in page
    assert 'name="robots" content="noindex,nofollow,noarchive"' in page
    assert "default-src 'none'" in page
    assert page.count('referrerpolicy="no-referrer"') == 4
    assert page.count("%24select=") == 2
    assert "donor_address" not in page
    assert "contract_contact_email_ad" not in page
