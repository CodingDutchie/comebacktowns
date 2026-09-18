from __future__ import annotations

import textwrap
import zipfile
from io import BytesIO
from pathlib import Path

import pytest

from pipeline.storage import LocalStore

SCOPE = {
    "state_fips": "36",
    "legal_types": ["city", "village"],
    "population": {"min": 1000, "max": 50000},
    "expected_count": {"min": 1, "max": 100},
    "regions": {
        "Capital Region": {"039": "Greene", "021": "Columbia"},
        "Hudson Valley": {"111": "Ulster"},
    },
}

# SUMLEV,STATE,COUNTY,PLACE,COUSUB,CONCIT,PRIMGEO_FLAG,FUNCSTAT,NAME,STNAME,ESTIMATESBASE2020,POPESTIMATE2020,...
POPEST = textwrap.dedent(
    """\
    SUMLEV,STATE,COUNTY,PLACE,COUSUB,CONCIT,PRIMGEO_FLAG,FUNCSTAT,NAME,STNAME,ESTIMATESBASE2020,POPESTIMATE2020,POPESTIMATE2024
    162,36,000,13002,00000,00000,0,A,Catskill village,New York,3800,3800,3900
    157,36,039,13002,00000,00000,0,A,Catskill village,New York,3800,3800,3900
    061,36,039,00000,13013,00000,0,A,Catskill town,New York,11000,11000,11200
    162,36,000,39727,00000,00000,0,A,Kingston city,New York,24000,24000,24100
    157,36,111,39727,00000,00000,0,A,Kingston city,New York,24000,24000,24100
    162,36,000,99001,00000,00000,0,S,Bigplace CDP,New York,5000,5000,5000
    157,36,039,99001,00000,00000,0,S,Bigplace CDP,New York,5000,5000,5000
    162,36,000,99002,00000,00000,0,A,Tiny village,New York,900,900,950
    157,36,039,99002,00000,00000,0,A,Tiny village,New York,900,900,950
    162,36,000,99003,00000,00000,0,A,Elsewhere village,New York,2000,2000,2000
    157,36,001,99003,00000,00000,0,A,Elsewhere village,New York,2000,2000,2000
    162,36,000,99004,00000,00000,0,A,Twin village,New York,2000,2000,2000
    157,36,039,99004,00000,00000,0,A,Twin village,New York,2000,2000,2000
    162,36,000,99005,00000,00000,0,A,Twin village,New York,3000,3000,3000
    157,36,021,99005,00000,00000,0,A,Twin village,New York,2900,2900,2900
    157,36,039,99005,00000,00000,0,A,Twin village,New York,100,100,100
    162,42,000,13002,00000,00000,0,A,Catskill village,Pennsylvania,3800,3800,3900
    """
)

GAZ = (
    "USPS\tGEOID\tANSICODE\tNAME\tLSAD\tFUNCSTAT\tALAND\tAWATER\tALAND_SQMI\tAWATER_SQMI\tINTPTLAT\tINTPTLONG        \n"
    "NY\t3613002\t02391588\tCatskill village\t47\tA\t5904025\t1500234\t2.28\t0.579\t42.214901\t-73.858674       \n"
    "NY\t3639727\t00979091\tKingston city\t25\tA\t1\t1\t1\t1\t41.930\t-74.005\n"
    "NY\t3699001\t0\tBigplace CDP\t57\tS\t1\t1\t1\t1\t42.0\t-74.0\n"
    "NY\t3699002\t0\tTiny village\t47\tA\t1\t1\t1\t1\t42.0\t-74.0\n"
    "NY\t3699003\t0\tElsewhere village\t47\tA\t1\t1\t1\t1\t42.0\t-74.0\n"
    "NY\t3699004\t0\tTwin village\t47\tA\t1\t1\t1\t1\t42.1\t-74.1\n"
    "NY\t3699005\t0\tTwin village\t47\tA\t1\t1\t1\t1\t42.2\t-74.2\n"
    "PA\t4213002\t0\tCatskill village\t47\tA\t1\t1\t1\t1\t40.0\t-77.0\n"
)


@pytest.fixture
def popest_bytes() -> bytes:
    return POPEST.encode()


@pytest.fixture
def gazetteer_zip() -> bytes:
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("2024_Gaz_place_national.txt", GAZ)
    return buf.getvalue()


@pytest.fixture
def scope() -> dict:
    return SCOPE


@pytest.fixture
def local_store(tmp_path: Path) -> LocalStore:
    return LocalStore(tmp_path / "raw")
