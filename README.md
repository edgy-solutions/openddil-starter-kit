# Starter kit: write an analytic unit and test it on recorded data

This kit lets you write an analytic unit and run it against a recording of a two-edge test system, on your own machine, with no broker and no cluster. If your unit passes here and keeps the four rules below, it can be reviewed for the real runner without being rewritten.

## Day one

You are a contributor to openddil-tactical-agents from your first day: your work goes into the public repository through pull requests, reviewed like anyone else's.

1. Fork or clone openddil-tactical-agents and install the hooks in that clone, before your first commit (see "Where your work goes"). Work from branch `algorithms-ports`, not `master`. It is open as a draft pull request and holds the runtime contract, the replay harness and the ported units. This kit's `harness/` is that branch's runtime. Base your branches on it until it merges.
2. Fetch the recording and check it ("Get the recording"). It isn't in git.
3. Run the template's tests and one replay ("Run it"). Both should pass on a fresh machine.
4. Read `DATA.md`, so you know what the recording holds and what it doesn't.
5. Pick a problem from `FIRST-PROBLEMS.md`. Each is a real gap, with its inputs, its acceptance test and the files it touches.
6. Open a branch for it and a draft pull request early. Anything from your own program goes in a private overlay (`tools/init-overlay.sh`), never in the public repo.

## What is here

| path | what |
|---|---|
| `data/` | The recording to date, by edge. Not in git: it comes from release `recording-rev30` ("Get the recording"). See `DATA.md` for what it holds and, more importantly, what it doesn't. |
| `SHA256SUMS` | The checksums of the recording's two tarballs and of every file in them. |
| `harness/` | The runtime your unit runs under, and the replay tool. It's the same code the edge runner uses, less the one module that connects to the broker. |
| `template/speed_watch/` | A small working unit: its `unit.yaml` and its Python. Copy this to start. |
| `template/tests/` | That unit's tests. They run with no network. |
| `FIRST-PROBLEMS.md` | Three real gaps to start on, each with its inputs, its acceptance test and the files it touches. |
| `tools/` | `init-overlay.sh` and its template (a private overlay skeleton), and the git hooks. See "Where your work goes". |

## Get the recording

The recording is too big for git, so it's attached to a release of this repository, one tarball per edge. From the kit's root (on Windows, in Git Bash):

```
gh release download recording-rev30 --repo edgy-solutions/openddil-starter-kit
tar -xf data-edge-01.tar
tar -xf data-edge-02.tar
sha256sum -c SHA256SUMS
```

Every line of the check should end `OK`. If one doesn't, download again before you trust anything the replay says. The tarballs can be deleted afterwards. A later recording comes as a new release, with its own sums.

## Run it

```
python -m venv .venv
.venv/bin/pip install -r requirements.txt      # Windows: .venv\Scripts\pip
.venv/bin/python -m pytest template/tests
.venv/bin/python run_replay.py template/speed_watch data/edge-01 out/speed_watch-edge-01.json
```

The last line replays the unit over one edge's recorded input and writes a JSON report: records read, what the unit emitted, and any step that failed.

## Where your work goes

openddil-tactical-agents is a public repository. You work in it as any contributor does:
- **One branch per unit**, opened as a pull request.
- **Hooks installed** in your clone before your first commit: `tools/hooks/install-hooks.sh --mode public <your clone>` (in this kit, copied from openddil-customer-bundle-example). List your program's names, data names and model names in `.git/info/private-terms`. The hooks refuse a commit or push that carries one, and that file never leaves your machine.
- **No private data.** Nothing from your program goes near the public repo: not its data, not its names, not its models.
- **Anything from a program lives in a private overlay.** `bash tools/init-overlay.sh <dir>` (in this kit) creates one: a private repo skeleton with its checks, its CI and its hooks already installed. Its README says what stays private and what may cross to public, and how. Its `checks.sh` runs against clones of the public openddil repositories: its `.env.example` names them, and its CI pins each one to a commit.

## What a unit is

A unit is a directory with a `unit.yaml` and one Python class with one method:

```python
class SpeedWatch(Unit):
    def step(self, sample, state):
        ...
        return {"anomaly": {"summary": "...", "evidence": {...}}}   # or None
```

`step` is called once per input record, per asset, in order.
- `sample` is a dict of the roles you declared.
- `state` is this asset's state: a dict of the fields you declared. Change it in place.
- `self.params` holds your parameters, from the YAML.

Every tunable constant goes in `params`, with a default, a range and a unit. A number that lives only in the code can't be changed or reviewed by anyone reading the YAML.

Use the sample's own time and never the clock. Then a replay gives the same answer every time, and your results can be compared row for row.

## The four rules

The runner loads a unit only if it keeps these. Rules 1, 3 and 4 are checked when the unit loads. Rule 2 is checked on every output as it is built: an output that breaks it is dropped and counted. The template's tests show each one.

**1. Declared inputs, by role.** You name the roles you read under `inputs.roles`, from the runtime's fixed vocabulary (`contract.ROLES` in `harness/algorithm_runtime/contract.py`). Your unit never sees the raw message. A role marked `required: true` means the step doesn't run for a record without it; check for an optional role yourself. A role the vocabulary doesn't have is refused. If you need a new one, ask: roles are added in the runtime, not in a unit.

**2. Outputs are declared kinds, with derived provenance.** You list each output under `outputs`, and `step` returns a payload for those kinds only. Your payload carries your result and nothing else. The runner builds the message around it: it marks the value as derived, copies the security labels from the source record, and stamps the unit's name, version and configuration hash. You don't set severity, labels or provenance, and a payload that tries is refused. An output from an unlabelled source stays unlabelled.

**3. No rollup the composability gate refuses.** Every unit declares a `composition`.
- `propagating` means another tier can safely build on the output.
- `terminal` means the result is lossy and has to stop here.

A `terminal` unit with an `upward` output is refused at load, because a lossy result must not be rolled up into a figure that looks exact.

**4. No network.** Your source may import only `__future__`, `math`, `dataclasses`, `typing` and `algorithm_runtime.contract`. `dependencies` must stay empty, because nothing is fetched at load. `open`, `eval`, `exec`, `getattr` and similar names are refused, and so are dunder attributes.

The import check guards against accidents in code that a person has reviewed. It is **not a sandbox**, so don't read it as one. A reviewer still reads every unit.

## Ways it can go wrong

- **Testing only on the data here.** Read `DATA.md` first. Several kinds of input aren't in this recording, so a unit that reads them will see nothing and pass.
- **Rates and memory.** A unit is measured over a recording before it runs anywhere (`run_replay.py --measure <unit-dir> <data/edge-xx> <out.json>`), and the runner refuses one that has no `measured` block or whose declared memory and CPU don't fit the container. The template has no `measured` block: measure your unit and add one, with the date and the machine you measured on (`harness/declaration.schema.json` lists its fields). Keep per-asset state small: state is per asset and there can be many assets.
- **State you can't read back.** Durable state is flat fields (numbers or strings), and it survives a restart. If you change a field's meaning, say how old stored state should be read.
