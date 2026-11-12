"""The one UCUM->pint dialect table.

Services import it from the generated bindings (openddil.common.v1.ucum);
add a unit here, never in a service. quantity.proto (lines 17-20) says unit
strings are UCUM codes; pint spells some of them differently, and this table
is that translation. Pure data: it imports nothing.
"""

UCUM_TO_PINT: dict[str, str] = {
    "[degF]": "degF",
    "[kn_i]": "knot",
    "gal_us": "gallon",
    "1": "dimensionless",
    "Cel": "degC",
}


def pint_unit(ucum: str) -> str:
    return UCUM_TO_PINT.get(ucum, ucum)
