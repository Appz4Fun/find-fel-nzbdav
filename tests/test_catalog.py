from find_fel_nzbdav.catalog import (
    CatalogRelease,
    CatalogTitle,
    dedupe_catalog_titles,
    normalize_catalog_title,
    render_catalog_payload,
)


def test_normalize_catalog_title_strips_4k_bluray_suffix_and_article():
    assert normalize_catalog_title("The Deer Hunter 4K Blu-ray") == "deer hunter"


def test_normalize_catalog_title_normalizes_punctuation_to_spaces():
    assert normalize_catalog_title("Spider-Man: No Way Home") == "spider man no way home"


def test_dedupe_catalog_titles_merges_releases_by_normalized_title_and_year():
    releases = [
        CatalogRelease(
            source="bluray-com",
            source_id="deer-hunter-uk",
            source_url="https://www.blu-ray.com/movies/The-Deer-Hunter-4K-Blu-ray/1/",
            title="The Deer Hunter 4K Blu-ray",
            normalized_title="deer hunter",
            year=1978,
            country="United Kingdom",
            release_date="2024-10-21",
            edition="Collector's Edition",
            studio="StudioCanal",
            video="2160p",
            hdr="Dolby Vision",
            discs="2",
            is_4k=True,
            is_dolby_vision=True,
        ),
        CatalogRelease(
            source="bluray-com",
            source_id="deer-hunter-us",
            source_url="https://www.blu-ray.com/movies/The-Deer-Hunter-4K-Blu-ray/2/",
            title="The Deer Hunter",
            normalized_title="deer hunter",
            year=1978,
            country="United States",
            release_date="2022-05-17",
            edition=None,
            studio="Shout Factory",
            video="2160p",
            hdr="HDR10",
            discs="3",
            is_4k=True,
            is_dolby_vision=False,
        ),
    ]

    assert dedupe_catalog_titles(releases) == [
        CatalogTitle(
            title="The Deer Hunter",
            normalized_title="deer hunter",
            year=1978,
            release_count=2,
            countries=("United Kingdom", "United States"),
            source_urls=(
                "https://www.blu-ray.com/movies/The-Deer-Hunter-4K-Blu-ray/1/",
                "https://www.blu-ray.com/movies/The-Deer-Hunter-4K-Blu-ray/2/",
            ),
            fel_status="unknown",
        )
    ]


def test_render_catalog_payload_includes_titles_and_optional_releases():
    release = CatalogRelease(
        source="bluray-com",
        source_id="spider-man-no-way-home-us",
        source_url="https://www.blu-ray.com/movies/Spider-Man-No-Way-Home-4K-Blu-ray/1/",
        title="Spider-Man: No Way Home",
        normalized_title="spider man no way home",
        year=2021,
        country="United States",
        release_date="2022-04-12",
        edition=None,
        studio="Sony Pictures",
        video="2160p",
        hdr="Dolby Vision",
        discs="2",
        is_4k=True,
        is_dolby_vision=True,
    )

    assert render_catalog_payload([release], include_releases=True) == {
        "source": "bluray-com",
        "count": 1,
        "titles": [
            {
                "title": "Spider-Man: No Way Home",
                "normalized_title": "spider man no way home",
                "year": 2021,
                "release_count": 1,
                "countries": ("United States",),
                "source_urls": (
                    "https://www.blu-ray.com/movies/Spider-Man-No-Way-Home-4K-Blu-ray/1/",
                ),
                "fel_status": "unknown",
            }
        ],
        "releases": [
            {
                "source": "bluray-com",
                "source_id": "spider-man-no-way-home-us",
                "source_url": "https://www.blu-ray.com/movies/Spider-Man-No-Way-Home-4K-Blu-ray/1/",
                "title": "Spider-Man: No Way Home",
                "normalized_title": "spider man no way home",
                "year": 2021,
                "country": "United States",
                "release_date": "2022-04-12",
                "edition": None,
                "studio": "Sony Pictures",
                "video": "2160p",
                "hdr": "Dolby Vision",
                "discs": "2",
                "is_4k": True,
                "is_dolby_vision": True,
                "fel_status": "unknown",
            }
        ],
    }
