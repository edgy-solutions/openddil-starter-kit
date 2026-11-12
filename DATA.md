# What the recording holds

Read this before you trust a result. A unit that reads a field this recording doesn't carry sees nothing, and passes.

The recording comes from a two-edge test system whose entities are generated tracks. It isn't an observation of anything real. It runs from 2026-11-08 01:52 UTC to 2026-11-11 02:36 UTC, on one software build, and covers 17 assets. It is a recording to date: this export stops at its last pull.

## Files

`data/<edge>/<topic>.<first-offset>-<last-offset>.gz`: gzip text, one record per line, four space-separated columns:

```
offset  broker-time-ms  key-base64  value-base64
```

Files of one topic join end to end in offset order, and may overlap by a record or two: `run_replay.py` handles that.

| edge | raw-sensor-stream | derived-sustainment | prognostics-changelog |
|---|---:|---:|---:|
| edge-01 | 470,889 | 470,890 | 238,111 |
| edge-02 | 418,618 | 418,621 | 197,154 |

- **raw-sensor-stream** is the input: `openddil.telemetry.v1.EntityTelemetryEvent` (bindings in `harness/openddil/`). This is what your unit is replayed over.
- **derived-sustainment** is what the production wear unit emitted from that input. You can read it as a worked example of an output.
- **prognostics-changelog** is that unit's state as it was written.

Asset names and callsigns aren't part of this export.

## What is NOT here

Whole streams that were not recorded:

- **Element telemetry** (per-component health). A unit that reads it can't be tested on this data.
- **Tactical events and telemetry windows** (the outputs of the other units).
- **Anything from a tier above the edge.**

Fields declared on the input message that never appear in these 889,507 records:

```
asset.callsign
kinematics.acceleration
kinematics.angular_velocity
kinematics.dead_reckoning
sustainment.thermal
sustainment.power
sustainment.fluids
sustainment.consumables
sustainment.wear
sustainment.value_provenance
provenance.source_sequence
provenance.relay_chain
provenance.producer_stamp
operational_state
```

So the input carries no fluid, consumable, wear, thermal or power values, and no operational state. A unit that trends those will produce nothing here.

## What is here, and how narrow it is

| assets | records | records per asset (min, median, max) |
|---:|---:|---|
| 17 | 889,507 | 52,312, 52,327, 52,341 |

Populated fields, with the number of records carrying each:

| field | records |
|---|---:|
| `asset` | 889,507 |
| `asset.asset_id` | 889,507 |
| `asset.cbm_schema` | 732,494 |
| `asset.configuration_baseline` | 837,166 |
| `asset.dis_entity_id` | 889,507 |
| `asset.dis_entity_type` | 889,507 |
| `asset.domain_authority` | 732,494 |
| `asset.force` | 889,507 |
| `asset.platform_type` | 889,507 |
| `asset.platform_variant` | 889,507 |
| `asset.subsystem` | 104,672 |
| `event_id` | 889,507 |
| `kinematics` | 889,507 |
| `kinematics.attitude` | 889,507 |
| `kinematics.position` | 889,507 |
| `kinematics.velocity` | 889,507 |
| `provenance` | 889,507 |
| `provenance.classification` | 889,507 |
| `provenance.edge_id` | 889,507 |
| `provenance.ingest_time` | 889,507 |
| `provenance.originator_nation` | 837,171 |
| `provenance.producer_id` | 889,507 |
| `provenance.region_id` | 889,507 |
| `provenance.releasable_to` | 52,328 |
| `provenance.sample_time` | 889,507 |
| `provenance.source_protocol` | 889,507 |
| `schema_revision` | 889,507 |
| `sustainment` | 889,507 |
| `sustainment.health` | 889,507 |

**Speed.** 889,507 records carry a velocity (units seen: m/s). Magnitude min 3.09, median 7.74, max 106.60; 0 records are under 1 m/s. These tracks essentially never stop, so stopped-to-moving behaviour isn't exercised here.

**Positions.** Geocentric latitude 7.1 to 47.7, longitude -128.8 to -89.0.

**Nation labels** (fictional), assets per label: (none): 1, ATL: 10, BDR: 6.
 Unlabelled assets: 1. An output from an unlabelled source must stay unlabelled, so test yours on one of these.


## Using it

The records' own sample time is what your unit should read. Broker time is when the record arrived, and a replay doesn't reproduce arrival order across assets. Per asset, the order is preserved.
