"""A fictional world for the tests: a GeoLite2 City CSV directory and links.txt.

Each country has three IPv4 /24s and one IPv6 /48. A few special networks are added:
- one with a registered country but no location (the fallback of SPEC 1.1);
- one whose location has a continent but no country (also falls back to the registered country);
- one with neither a location nor a registered country (assigned to ZZ);
- one overlapping an earlier network (to be dropped).
"""
from __future__ import annotations

import csv
import ipaddress
from pathlib import Path

# country code, continent, latitude, longitude, land neighbours
COUNTRIES = [
    ("US", "NA", 39.8, -98.6, "CA MX"),
    ("CA", "NA", 56.0, -96.0, "US"),
    ("MX", "NA", 23.6, -102.5, "US GT"),
    ("GT", "NA", 15.7, -90.2, "MX"),
    ("BR", "SA", -10.0, -52.0, "AR CO"),
    ("AR", "SA", -34.0, -64.0, "BR CL"),
    ("CL", "SA", -33.5, -70.7, "AR"),
    ("CO", "SA", 4.6, -74.1, "BR"),
    ("PT", "EU", 39.4, -8.2, "ES"),
    ("ES", "EU", 40.4, -3.7, "PT FR"),
    ("FR", "EU", 46.6, 2.2, "ES DE"),
    ("DE", "EU", 51.2, 10.4, "FR PL"),
    ("PL", "EU", 52.0, 19.1, "DE"),
    ("MA", "AF", 31.8, -7.1, ""),
    ("NG", "AF", 9.1, 8.7, ""),
    ("ZA", "AF", -30.6, 22.9, ""),
    ("EG", "AF", 26.8, 30.8, ""),
    ("CI", "AF", 7.5, -5.5, ""),
    ("AE", "AS", 23.4, 53.8, ""),
    ("IN", "AS", 21.0, 78.0, ""),
    ("SG", "AS", 1.35, 103.8, ""),
    ("JP", "AS", 36.2, 138.3, ""),
    ("CN", "AS", 35.0, 105.0, ""),
    ("AU", "OC", -25.3, 133.8, ""),
    ("NZ", "OC", -41.0, 174.0, ""),
    ("AQ", "AN", -75.0, 0.0, ""),
]

CABLES = {
    "west-africa": "PT MA CI NG ZA",
    "sea-me-we": "FR EG AE IN SG",
    "trans-pacific": "US JP",
    "tasman": "AU NZ",
    "south-atlantic": "BR NG",
    "phantom": "XX PT ES",          # XX is not in the GeoIP data and must be ignored
}

CONTINENT_ONLY_ID = 9000            # a location with a continent but no country
NO_COUNTRY_NET = "10.250.0.0/24"    # assigned to ZZ
REGISTERED_ONLY_NET = "10.251.0.0/24"   # registered country JP only
CONTINENT_ONLY_NET = "10.252.0.0/24"    # location has a continent only, registered country DE
OVERLAP_NET = "10.0.0.128/25"       # inside the first /24 of US, to be dropped


def geoname_id(i: int) -> str:
    return str(1000 + i)


def country_id(code: str) -> str:
    return geoname_id(next(i for i, c in enumerate(COUNTRIES) if c[0] == code))


def write_geoip(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    with open(directory / "GeoLite2-City-Locations-en.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["geoname_id", "locale_code", "continent_code", "continent_name",
                    "country_iso_code", "country_name"])
        for i, (code, cont, *_rest) in enumerate(COUNTRIES):
            w.writerow([geoname_id(i), "en", cont, "", code, ""])
        w.writerow([CONTINENT_ONLY_ID, "en", "EU", "Europe", "", ""])
    header = ["network", "geoname_id", "registered_country_geoname_id",
              "represented_country_geoname_id", "is_anonymous_proxy", "is_satellite_provider",
              "postal_code", "latitude", "longitude", "accuracy_radius", "is_anycast"]

    def row(net, gid, reg, lat, lon):
        return [net, gid, reg, "", "0", "0", "", "" if lat is None else lat,
                "" if lon is None else lon, "", ""]

    with open(directory / "GeoLite2-City-Blocks-IPv4.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        for i, (code, _, lat, lon, _) in enumerate(COUNTRIES):
            for j in range(3):
                w.writerow(row(f"10.{i}.{j}.0/24", geoname_id(i), geoname_id(i), lat + j * 0.1, lon))
        w.writerow(row(OVERLAP_NET, country_id("CN"), country_id("CN"), 35.0, 105.0))
        w.writerow(row(NO_COUNTRY_NET, "", "", None, None))
        w.writerow(row(REGISTERED_ONLY_NET, "", country_id("JP"), None, None))
        w.writerow(row(CONTINENT_ONLY_NET, CONTINENT_ONLY_ID, country_id("DE"), 50.0, 8.0))
    with open(directory / "GeoLite2-City-Blocks-IPv6.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        for i, (code, _, lat, lon, _) in enumerate(COUNTRIES):
            w.writerow(row(f"2001:db8:{i:x}::/48", geoname_id(i), geoname_id(i), lat, lon))
    return directory


def links_text() -> str:
    lines = ["# links for the tests"]
    lines += [f"cable:{cid}  {countries}" for cid, countries in CABLES.items()]
    pairs = set()
    for code, *_rest, neighbours in COUNTRIES:
        for other in neighbours.split():
            pairs.add(tuple(sorted((code, other))))
    lines += [f"border  {a} {b}" for a, b in sorted(pairs)]
    return "\n".join(lines) + "\n"


def write_links(path: Path) -> Path:
    path.write_text(links_text(), encoding="utf-8")
    return path


def cidr_range(cidr: str) -> tuple[int, int]:
    net = ipaddress.ip_network(cidr)
    return int(net.network_address), int(net.broadcast_address)
