#!/bin/bash
# Regenerate ONLY rjsf.json, skipping environment resolution entirely.
#
# Two steps:
#   1. Run wt-registry against the ALREADY-INSTALLED compiled workflow env.
#   2. Feed that registry dump into wt-compiler's schema-generation logic
#      to build the final rjsf-overrides-applied rjsf.json.
#
# Usage: ./dev/regenerate_rjsf.sh
#
# Run make build first if you've changed ext-belize tasks.
# Run this anytime you've only changed spec.yaml or rjsf-overrides.
#
# NOTE: this does NOT regenerate dags/run_sequential.py. Structural spec.yaml
# changes (new/removed steps, changed partial values, mapvalues/map wiring)
# need a full `make compile`/`make recompile` to take effect in the executable DAG.

set -e

GENERATED_DIR="ecoscope-workflows-belize-patrol-report-workflow"
REGISTRY_BIN="${GENERATED_DIR}/.pixi/envs/default/bin/wt-registry"
REGISTRY_JSON="/tmp/wt_registry_belize_patrol_report.json"

if [ ! -x "$REGISTRY_BIN" ]; then
    echo "Error: $REGISTRY_BIN not found. Run 'make compile' once first."
    exit 1
fi

echo "1/2: Dumping task registry from installed env..."
time "$REGISTRY_BIN" --format json \
    --package ecoscope.platform.tasks \
    --package ecoscope_workflows_ext_custom.tasks \
    --package ecoscope_workflows_ext_belize.tasks \
    > "$REGISTRY_JSON"

echo ""
echo "2/2: Building rjsf.json from registry dump + spec.yaml..."
pixi run --manifest-path pixi.toml python -c "
import json
import ruamel.yaml

from wt_contracts.registry import RegistryOutput
from wt_compiler.spec import KnownTask, Spec, TaskTag, known_tasks
from wt_compiler.compiler import DagCompiler

with open('$REGISTRY_JSON') as f:
    registry_output = RegistryOutput.model_validate_json(f.read())

discovered: dict = {}
for entry in registry_output.entries.values():
    public_module_path = entry.public_module_path
    function_name = entry.function_name
    metadata = entry.metadata
    json_schema = dict(entry.json_schema)
    importable_reference = f'{public_module_path}.{function_name}'
    tags = [TaskTag(t) for t in metadata.tags if t in [tt.value for tt in TaskTag]]

    known_task = KnownTask(
        importable_reference=importable_reference,
        tags=tags,
        registry_ref=0,
        json_schema=json_schema,
        description=metadata.description or None,
    )
    if function_name not in discovered:
        discovered[function_name] = {public_module_path: known_task}
    else:
        known_task.registry_ref = len(discovered[function_name])
        discovered[function_name][public_module_path] = known_task

known_tasks.clear()
known_tasks.update(discovered)

yaml = ruamel.yaml.YAML(typ='safe')
with open('spec.yaml') as f:
    spec_dict = yaml.load(f)
spec = Spec(**spec_dict)

dc = DagCompiler(
    spec=spec,
    pkg_name_prefix='ecoscope-workflows',
    results_env_var='ECOSCOPE_WORKFLOWS_RESULTS',
)
params_schema_hierarchical = dc.get_params_jsonschema(flat=False)
if spec.rjsf_overrides:
    params_schema_hierarchical = spec.rjsf_overrides.apply_overrides(params_schema_hierarchical)

result = params_schema_hierarchical.model_dump(by_alias=True, exclude_none=True)

from pathlib import Path
out = Path('$GENERATED_DIR') / 'ecoscope_workflows_belize_patrol_report_workflow' / 'rjsf.json'
out.write_text(json.dumps(result, indent=2) + '\n')
print('written:', out)
"
