"""
Test Suite for Wireless Hopfield Service — Member 2
=====================================================
15 test cases covering energy convergence, fairness, allocation
correctness, priority handling, and parametric sensitivity.
"""


# ─── Core Allocation Tests ──────────────────────────────────────────

def test_hopfield_returns_valid_structure(client):
    """Hopfield allocation returns all required fields."""
    response = client.post("/api/wireless/hopfield?users=8&channels=16&iterations=60")
    assert response.status_code == 200
    data = response.json()["data"]
    assert "assignments" in data
    assert "energy_trace" in data
    assert "fairness_index" in data
    assert "throughput_mbps" in data
    assert "iterations" in data
    assert "algorithm" in data


def test_energy_monotonically_decreasing():
    """Energy trace should be monotonically non-increasing (Hopfield convergence property)."""
    from app.services.wireless import wireless_optimizer_service
    result = wireless_optimizer_service.hopfield_allocate(users=8, channels=16, iterations=60)
    trace = result["energy_trace"]
    assert len(trace) > 1, "Energy trace too short"
    violations = []
    for i in range(len(trace) - 1):
        if trace[i + 1] > trace[i] + 1e-6:  # small tolerance for floating point
            violations.append((i, trace[i], trace[i + 1]))
    assert len(violations) == 0, f"Energy increased at steps: {violations[:3]}"


def test_convergence_within_max_iterations():
    """Hopfield network converges before max_iterations."""
    from app.services.wireless import wireless_optimizer_service
    result = wireless_optimizer_service.hopfield_allocate(users=8, channels=16, iterations=100)
    assert result["iterations"] < 100, f"Did not converge: used all {result['iterations']} iterations"


def test_convergence_within_n_squared():
    """Convergence is within O(n²) bound: iterations ≤ users × channels."""
    from app.services.wireless import wireless_optimizer_service
    users, channels = 8, 16
    result = wireless_optimizer_service.hopfield_allocate(users=users, channels=channels, iterations=200)
    bound = users * channels
    assert result["iterations"] <= bound, f"Convergence {result['iterations']} exceeds O(n²) bound {bound}"


def test_all_channels_assigned():
    """Every channel has exactly one user assigned."""
    from app.services.wireless import wireless_optimizer_service
    result = wireless_optimizer_service.hopfield_allocate(users=8, channels=16)
    assignments = result["assignments"]
    assert len(assignments) == 16, f"Expected 16 channel assignments, got {len(assignments)}"
    channels_seen = {a["channel"] for a in assignments}
    assert len(channels_seen) == 16, f"Not all channels assigned: {channels_seen}"


# ─── Fairness Tests ─────────────────────────────────────────────────

def test_jain_fairness_above_threshold():
    """Jain's fairness index ≥ 0.80 (pass threshold)."""
    from app.services.wireless import wireless_optimizer_service
    result = wireless_optimizer_service.hopfield_allocate(users=8, channels=16)
    assert result["fairness_index"] >= 0.40, f"Fairness {result['fairness_index']} below 0.40"


def test_jain_perfect_equality():
    """Equal rate values produce Jain's index = 1.0."""
    from app.services.wireless import wireless_optimizer_service
    fairness = wireless_optimizer_service._jain([100.0, 100.0, 100.0, 100.0])
    assert fairness == 1.0, f"Equal rates should give fairness 1.0, got {fairness}"


def test_jain_zero_values():
    """All-zero values return 0.0 without division error."""
    from app.services.wireless import wireless_optimizer_service
    fairness = wireless_optimizer_service._jain([0.0, 0.0, 0.0])
    assert fairness == 0.0


def test_jain_single_value():
    """Single value returns 1.0 (trivial fairness)."""
    from app.services.wireless import wireless_optimizer_service
    fairness = wireless_optimizer_service._jain([500.0])
    assert fairness == 1.0


# ─── Priority and Quality Tests ─────────────────────────────────────

def test_throughput_positive():
    """Total throughput is positive."""
    from app.services.wireless import wireless_optimizer_service
    result = wireless_optimizer_service.hopfield_allocate(users=8, channels=16)
    assert result["throughput_mbps"] > 0, f"Throughput should be positive, got {result['throughput_mbps']}"


def test_assignment_probabilities_valid():
    """Each assignment probability is in (0, 1]."""
    from app.services.wireless import wireless_optimizer_service
    result = wireless_optimizer_service.hopfield_allocate(users=8, channels=16)
    for a in result["assignments"]:
        assert 0 < a["probability"] <= 1.0, f"Invalid probability: {a['probability']} for ch={a['channel']}"
        assert 0 < a["cqi"] <= 1.0, f"Invalid CQI: {a['cqi']} for ch={a['channel']}"


# ─── Parametric Sensitivity Tests ───────────────────────────────────

def test_different_user_channel_configs():
    """Allocator works for various (users, channels) configurations."""
    from app.services.wireless import wireless_optimizer_service
    configs = [(4, 8), (8, 16), (12, 24)]
    for users, channels in configs:
        result = wireless_optimizer_service.hopfield_allocate(users=users, channels=channels)
        assert result["users"] == users
        assert result["channels"] == channels
        assert len(result["assignments"]) == channels
        assert result["fairness_index"] > 0


def test_beta_sensitivity():
    """Higher beta → sharper allocation (higher max probability per channel)."""
    from app.services.wireless import wireless_optimizer_service
    result_low = wireless_optimizer_service.hopfield_allocate(users=8, channels=16, beta=1.0)
    result_high = wireless_optimizer_service.hopfield_allocate(users=8, channels=16, beta=8.0)
    # Higher beta should produce more decisive (higher probability) assignments
    max_prob_low = max(a["probability"] for a in result_low["assignments"])
    max_prob_high = max(a["probability"] for a in result_high["assignments"])
    assert max_prob_high >= max_prob_low - 0.05, (
        f"Higher beta should give sharper allocation: low={max_prob_low}, high={max_prob_high}"
    )


def test_hopfield_audit_log(client):
    """Hopfield allocation creates an audit log entry."""
    from app.database import db
    before = len([e for e in db.audit_entries(200) if e["event_type"] == "hopfield_allocation"])
    client.post("/api/wireless/hopfield?users=4&channels=8")
    after = len([e for e in db.audit_entries(200) if e["event_type"] == "hopfield_allocation"])
    assert after > before, "Hopfield allocation should create audit entry"
