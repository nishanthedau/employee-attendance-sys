from app.services.geo_service import haversine_meters, is_within_radius

DELHI = (28.6139, 77.2090)
MUMBAI = (19.0760, 72.8777)
NEAR = (28.6139, 77.2100)  # ~100m east of Delhi point at this latitude


def test_haversine_same_point_is_zero():
    assert haversine_meters(*DELHI, *DELHI) == 0


def test_haversine_delhi_mumbai_distance():
    d = haversine_meters(*DELHI, *MUMBAI)
    assert 1_100_000 < d < 1_300_000


def test_haversine_close_points():
    d = haversine_meters(*DELHI, *NEAR)
    assert 90 < d < 130


def test_within_radius_true():
    assert is_within_radius(*DELHI, *NEAR, 150)


def test_within_radius_false():
    assert not is_within_radius(*DELHI, *NEAR, 50)


def test_boundary_inclusive():
    radius = haversine_meters(*DELHI, *NEAR)
    assert is_within_radius(*DELHI, *NEAR, radius)
