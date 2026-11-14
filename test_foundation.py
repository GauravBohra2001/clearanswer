"""Foundation-layer tests. Run from the repo root with the venv active:

    source venv/bin/activate && python test_foundation.py
"""
import sys

sys.path.insert(0, ".")

from core.loader import TCGARelease
from core.evidence import ClaimResult, Evidence, supported, contradicted, insufficient
from core.trace import TraceCollector, TraceEntry
from core.guard import pre_check, post_check
from tools.data_tool import DataTool
from tools.schema_tool import SchemaTool
from tools.manifest_tool import ManifestTool

release = TCGARelease("oncosys-hackathon-challenge/data/tcga-brca/raw/")

# Test 1 ---------------------------------------------------------------------
count = release.count_primary_tumors()
print(f"Test 1 - Primary tumors: {count}")
assert count == 1101, f"Expected 1101, got {count}"

# Test 2 ---------------------------------------------------------------------
count_all = release.count_with_all_layers()
print(f"Test 2 - With all layers: {count_all}")
assert count_all == 535, f"Expected 535, got {count_all}"

# Test 3 ---------------------------------------------------------------------
dist = release.subtype_distribution()
print(f"Test 3 - Subtype distribution: {dist}")
total_with_subtype = sum(dist.values())
assert total_with_subtype == 844, f"Expected 844 total, got {total_with_subtype}"

# Test 4 ---------------------------------------------------------------------
try:
    ClaimResult(
        claim_text="test",
        claim_verdict="contradicted",
        correct_value="",
        confidence="high",
        severity="high",
        evidence=[],
        reasoning="test",
    )
    assert False, "Should have raised ValueError!"
except ValueError as e:
    print(f"Test 4 - Contract enforced (contradicted no value): {e}")

# Test 5 ---------------------------------------------------------------------
try:
    ClaimResult(
        claim_text="test",
        claim_verdict="supported",
        correct_value="",
        confidence="high",
        severity="none",
        evidence=[],
        reasoning="test",
    )
    assert False, "Should have raised ValueError!"
except ValueError as e:
    print(f"Test 5 - Contract enforced (supported no evidence): {e}")

# Test 6 ---------------------------------------------------------------------
result = insufficient("test claim", "no hormone therapy data found")
print(f"Test 6 - Insufficient evidence OK: verdict={result.claim_verdict}")
assert result.claim_verdict == "insufficient_evidence"

# Test 7 ---------------------------------------------------------------------
st = SchemaTool(release)
cols = st.execute({"layer": "clinical", "action": "columns"})
print(f"Test 7 - Clinical has {len(cols['columns'])} columns")
assert "PAM50Call_RNAseq" in cols["columns"], "PAM50Call_RNAseq missing!"

# Test 8 ---------------------------------------------------------------------
dt = DataTool(release)
pam50 = dt.execute({
    "layer": "clinical",
    "operation": "value_counts",
    "column": "PAM50Call_RNAseq",
})
print(f"Test 8 - PAM50 distribution: {pam50['result']}")
assert pam50["ok"], pam50
# Across all samples (no primary_only filter): LumA is still the largest.
assert max(pam50["result"], key=pam50["result"].get) == "LumA", pam50["result"]

# Test 9 ---------------------------------------------------------------------
mt = ManifestTool(release)
mc = mt.execute({"action": "count_samples"})
print(f"Test 9 - Manifest count: {mc}")
assert mc["ok"] and mc["total_in_manifest"] == 1247, mc

# Test 10 --------------------------------------------------------------------
issues = pre_check("We recommend prescribing tamoxifen for ER+ patients")
print(f"Test 10 - Guard caught {len(issues)} issues: {issues}")
assert len(issues) > 0, "Guard should have caught clinical recommendation!"

# Test 11 --------------------------------------------------------------------
issues2 = pre_check("62% of tumors are Luminal A subtype")
print(f"Test 11 - Guard passed clean claim: {len(issues2)} issues")
assert len(issues2) == 0, issues2

# Test 12 --------------------------------------------------------------------
tc = TraceCollector()
with tc.start_step("test_agent", "plan") as step:
    step.reasoning = "Testing the trace system"
    step.output_data = {"test": True}
print(f"Test 12 - Trace has {len(tc.entries)} entries")
print(tc.to_markdown())

# Test 13 --------------------------------------------------------------------
search = st.execute({"layer": "clinical", "action": "search_columns", "query": "therap"})
print(f"Test 13 - Columns matching 'therap': {search}")
assert search["ok"] and search["n_hits"] > 0, search

print("\n✅ ALL 13 FOUNDATION TESTS PASSED")
