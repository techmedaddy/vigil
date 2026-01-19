"""
Tests for Phase 6 Policy Engine & Custom Rules
"""

import pytest
from datetime import datetime
from unittest.mock import Mock, AsyncMock, patch, MagicMock

from app.core.policy import (
    Policy,
    PolicyRegistry,
    Severity,
    ActionType,
    metric_exceeds,
    metric_below,
    all_conditions,
    any_condition,
    evaluate_policies,
    get_policy_registry,
    initialize_policies,
    load_policies_from_yaml,
    load_policies_from_json,
)


class TestPolicyConditions:
    """Test policy condition functions"""
    
    def test_metric_exceeds_condition(self):
        """Test metric exceeds threshold condition"""
        condition = metric_exceeds("cpu_percent", 80)
        
        # Should trigger
        assert condition({"cpu_percent": 90}) is True
        assert condition({"cpu_percent": 80.1}) is True
        
        # Should not trigger
        assert condition({"cpu_percent": 80}) is False
        assert condition({"cpu_percent": 70}) is False
        assert condition({"cpu_percent": 0}) is False
    
    def test_metric_below_condition(self):
        """Test metric below threshold condition"""
        condition = metric_below("disk_free_percent", 10)
        
        # Should trigger
        assert condition({"disk_free_percent": 5}) is True
        assert condition({"disk_free_percent": 9.9}) is True
        
        # Should not trigger
        assert condition({"disk_free_percent": 10}) is False
        assert condition({"disk_free_percent": 20}) is False
    
    def test_all_conditions(self):
        """Test AND combination of conditions"""
        condition = all_conditions(
            metric_exceeds("cpu_percent", 80),
            metric_exceeds("memory_percent", 75)
        )
        
        # Both conditions met
        assert condition({"cpu_percent": 85, "memory_percent": 80}) is True
        
        # Only one condition met
        assert condition({"cpu_percent": 85, "memory_percent": 70}) is False
        assert condition({"cpu_percent": 70, "memory_percent": 80}) is False
        
        # No conditions met
        assert condition({"cpu_percent": 70, "memory_percent": 70}) is False
    
    def test_any_condition(self):
        """Test OR combination of conditions"""
        condition = any_condition(
            metric_exceeds("cpu_percent", 90),
            metric_exceeds("memory_percent", 90)
        )
        
        # Both conditions met
        assert condition({"cpu_percent": 95, "memory_percent": 95}) is True
        
        # Only one condition met
        assert condition({"cpu_percent": 95, "memory_percent": 70}) is True
        assert condition({"cpu_percent": 70, "memory_percent": 95}) is True
        
        # No conditions met
        assert condition({"cpu_percent": 70, "memory_percent": 70}) is False


class TestPolicyClass:
    """Test Policy class"""
    
    def test_policy_creation(self):
        """Test creating a policy instance"""
        policy = Policy(
            name="test-policy",
            description="Test policy",
            condition=metric_exceeds("cpu_percent", 80),
            action=ActionType.SCALE_UP,
            severity=Severity.WARNING,
            target="web-*",
            enabled=True,
            params={"replicas": 2},
        )
        
        assert policy.name == "test-policy"
        assert policy.description == "Test policy"
        assert policy.severity == Severity.WARNING
        assert policy.target == "web-*"
        assert policy.enabled is True
        assert policy.params == {"replicas": 2}
    
    def test_policy_evaluate(self):
        """Test policy evaluation"""
        policy = Policy(
            name="high-cpu",
            condition=metric_exceeds("cpu_percent", 80),
            action=ActionType.SCALE_UP,
        )
        
        # Should trigger
        assert policy.evaluate({"cpu_percent": 90}) is True
        
        # Should not trigger
        assert policy.evaluate({"cpu_percent": 70}) is False
    
    def test_policy_evaluate_disabled(self):
        """Test disabled policy does not evaluate"""
        policy = Policy(
            name="high-cpu",
            condition=metric_exceeds("cpu_percent", 80),
            action=ActionType.SCALE_UP,
            enabled=False,
        )
        
        # Should not trigger even if condition met
        assert policy.evaluate({"cpu_percent": 90}) is False
    
    def test_policy_matches_target(self):
        """Test target matching"""
        policy = Policy(
            name="test",
            condition=lambda m: True,
            action=ActionType.CUSTOM,
            target="web-*",
        )
        
        # Should match
        assert policy.matches_target("web-server-01") is True
        assert policy.matches_target("web-api") is True
        
        # Should not match
        assert policy.matches_target("api-server") is False
    
    def test_policy_matches_target_all(self):
        """Test target 'all' matches everything"""
        policy = Policy(
            name="test",
            condition=lambda m: True,
            action=ActionType.CUSTOM,
            target="all",
        )
        
        assert policy.matches_target("web-server") is True
        assert policy.matches_target("api-server") is True
        assert policy.matches_target("anything") is True
    
    def test_policy_to_dict(self):
        """Test policy serialization to dictionary"""
        policy = Policy(
            name="test-policy",
            description="Test description",
            condition=lambda m: True,
            action=ActionType.SCALE_UP,
            severity=Severity.CRITICAL,
            target="all",
            enabled=True,
            params={"replicas": 3},
            auto_remediate=False,
        )
        
        result = policy.to_dict()
        
        assert result["name"] == "test-policy"
        assert result["description"] == "Test description"
        assert result["severity"] == "critical"
        assert result["target"] == "all"
        assert result["enabled"] is True
        assert result["params"] == {"replicas": 3}
        assert result["auto_remediate"] is False


class TestPolicyRegistry:
    """Test PolicyRegistry class"""
    
    @pytest.fixture
    def registry(self):
        """Create a fresh registry for each test"""
        return PolicyRegistry()
    
    @pytest.fixture
    def sample_policy(self):
        """Create a sample policy"""
        return Policy(
            name="test-policy",
            condition=metric_exceeds("cpu_percent", 80),
            action=ActionType.SCALE_UP,
            severity=Severity.WARNING,
        )
    
    def test_register_policy(self, registry, sample_policy):
        """Test registering a policy"""
        registry.register(sample_policy)
        
        assert len(registry.get_all()) == 1
        assert registry.get("test-policy") == sample_policy
    
    def test_register_duplicate_policy_fails(self, registry, sample_policy):
        """Test registering duplicate policy raises error"""
        registry.register(sample_policy)
        
        with pytest.raises(ValueError, match="already registered"):
            registry.register(sample_policy)
    
    def test_unregister_policy(self, registry, sample_policy):
        """Test unregistering a policy"""
        registry.register(sample_policy)
        registry.unregister("test-policy")
        
        assert len(registry.get_all()) == 0
        assert registry.get("test-policy") is None
    
    def test_unregister_nonexistent_policy_fails(self, registry):
        """Test unregistering non-existent policy raises error"""
        with pytest.raises(KeyError, match="not found"):
            registry.unregister("nonexistent")
    
    def test_get_enabled_policies(self, registry):
        """Test getting only enabled policies"""
        policy1 = Policy(
            name="policy1",
            condition=lambda m: True,
            action=ActionType.CUSTOM,
            enabled=True,
        )
        policy2 = Policy(
            name="policy2",
            condition=lambda m: True,
            action=ActionType.CUSTOM,
            enabled=False,
        )
        
        registry.register(policy1)
        registry.register(policy2)
        
        enabled = registry.get_enabled()
        
        assert len(enabled) == 1
        assert enabled[0].name == "policy1"
    
    def test_get_policies_by_severity(self, registry):
        """Test filtering policies by severity"""
        policy1 = Policy(
            name="policy1",
            condition=lambda m: True,
            action=ActionType.CUSTOM,
            severity=Severity.WARNING,
        )
        policy2 = Policy(
            name="policy2",
            condition=lambda m: True,
            action=ActionType.CUSTOM,
            severity=Severity.CRITICAL,
        )
        policy3 = Policy(
            name="policy3",
            condition=lambda m: True,
            action=ActionType.CUSTOM,
            severity=Severity.WARNING,
        )
        
        registry.register(policy1)
        registry.register(policy2)
        registry.register(policy3)
        
        warnings = registry.get_by_severity(Severity.WARNING)
        criticals = registry.get_by_severity(Severity.CRITICAL)
        
        assert len(warnings) == 2
        assert len(criticals) == 1
    
    def test_enable_disable_policy(self, registry, sample_policy):
        """Test enabling and disabling policies"""
        registry.register(sample_policy)
        
        # Initially enabled (default)
        assert sample_policy.enabled is True
        
        # Disable
        registry.disable_policy("test-policy")
        assert sample_policy.enabled is False
        
        # Enable
        registry.enable_policy("test-policy")
        assert sample_policy.enabled is True
    
    def test_list_policies(self, registry):
        """Test listing all policies as dictionaries"""
        policy = Policy(
            name="test-policy",
            description="Test",
            condition=lambda m: True,
            action=ActionType.SCALE_UP,
            severity=Severity.INFO,
            target="all",
            enabled=True,
            params={"key": "value"},
        )
        
        registry.register(policy)
        policies = registry.list_policies()
        
        assert "test-policy" in policies
        assert policies["test-policy"]["name"] == "test-policy"
        assert policies["test-policy"]["severity"] == "info"


class TestPolicyEvaluation:
    """Test policy evaluation engine"""
    
    @pytest.mark.asyncio
    async def test_evaluate_policies_no_violations(self):
        """Test evaluation with no violations"""
        registry = get_policy_registry()
        
        # Clear registry
        for policy_name in list(registry._policies.keys()):
            registry.unregister(policy_name)
        
        policy = Policy(
            name="test-policy",
            condition=metric_exceeds("cpu_percent", 90),
            action=ActionType.SCALE_UP,
            enabled=True,
            auto_remediate=False,  # Disable auto-remediate for test
        )
        registry.register(policy)
        
        # Metrics don't trigger policy
        result = await evaluate_policies({"cpu_percent": 70})
        
        assert len(result["violations"]) == 0
        assert len(result["actions_triggered"]) == 0
    
    @pytest.mark.asyncio
    async def test_evaluate_policies_with_violations(self):
        """Test evaluation with violations detected"""
        registry = get_policy_registry()
        
        # Clear registry
        for policy_name in list(registry._policies.keys()):
            registry.unregister(policy_name)
        
        policy = Policy(
            name="high-cpu",
            description="High CPU usage",
            condition=metric_exceeds("cpu_percent", 80),
            action=ActionType.SCALE_UP,
            severity=Severity.WARNING,
            enabled=True,
            auto_remediate=False,  # Disable auto-remediate for test
        )
        registry.register(policy)
        
        # Metrics trigger policy
        result = await evaluate_policies({"cpu_percent": 90})
        
        assert len(result["violations"]) == 1
        violation = result["violations"][0]
        assert violation["policy_name"] == "high-cpu"
        assert violation["severity"] == "warning"
        assert "timestamp" in violation
    
    @pytest.mark.asyncio
    async def test_evaluate_policies_target_filtering(self):
        """Test policy evaluation with target filtering"""
        registry = get_policy_registry()
        
        # Clear registry
        for policy_name in list(registry._policies.keys()):
            registry.unregister(policy_name)
        
        policy1 = Policy(
            name="web-policy",
            condition=metric_exceeds("cpu_percent", 80),
            action=ActionType.SCALE_UP,
            target="web-*",
            enabled=True,
            auto_remediate=False,
        )
        policy2 = Policy(
            name="api-policy",
            condition=metric_exceeds("cpu_percent", 80),
            action=ActionType.SCALE_UP,
            target="api-*",
            enabled=True,
            auto_remediate=False,
        )
        
        registry.register(policy1)
        registry.register(policy2)
        
        # Only web-policy should match
        result = await evaluate_policies({"cpu_percent": 90}, target="web-server-01")
        
        assert len(result["violations"]) == 1
        assert result["violations"][0]["policy_name"] == "web-policy"


class TestPolicyLoading:
    """Test loading policies from configuration files"""
    
    def test_load_policies_from_yaml(self, tmp_path):
        """Test loading policies from YAML file"""
        yaml_content = """
policies:
  - name: high-cpu
    description: "High CPU alert"
    severity: warning
    target: "web-*"
    enabled: true
    auto_remediate: true
    condition:
      type: metric_exceeds
      metric: cpu_percent
      threshold: 90
    action: scale-up
    params:
      replicas: 2
"""
        yaml_file = tmp_path / "test_policies.yaml"
        yaml_file.write_text(yaml_content)
        
        policies = load_policies_from_yaml(str(yaml_file))
        
        assert len(policies) == 1
        policy = policies[0]
        assert policy.name == "high-cpu"
        assert policy.description == "High CPU alert"
        assert policy.severity == Severity.WARNING
        assert policy.target == "web-*"
        assert policy.enabled is True
        assert policy.auto_remediate is True
        assert policy.params == {"replicas": 2}
    
    def test_load_policies_from_json(self, tmp_path):
        """Test loading policies from JSON file"""
        json_content = {
            "policies": [
                {
                    "name": "low-memory",
                    "description": "Low memory warning",
                    "severity": "critical",
                    "target": "all",
                    "enabled": True,
                    "auto_remediate": False,
                    "condition": {
                        "type": "metric_below",
                        "metric": "memory_free_percent",
                        "threshold": 10
                    },
                    "action": "custom",
                    "params": {"notify": True}
                }
            ]
        }
        
        import json
        json_file = tmp_path / "test_policies.json"
        json_file.write_text(json.dumps(json_content))
        
        policies = load_policies_from_json(str(json_file))
        
        assert len(policies) == 1
        policy = policies[0]
        assert policy.name == "low-memory"
        assert policy.severity == Severity.CRITICAL
    
    def test_load_policies_from_yaml_complex_conditions(self, tmp_path):
        """Test loading policies with complex condition combinations"""
        yaml_content = """
policies:
  - name: resource-exhaustion
    description: "CPU and memory both high"
    severity: critical
    target: "all"
    enabled: true
    condition:
      type: all
      conditions:
        - type: metric_exceeds
          metric: cpu_percent
          threshold: 85
        - type: metric_exceeds
          metric: memory_percent
          threshold: 85
    action: scale-up
    params:
      replicas: 3
"""
        yaml_file = tmp_path / "complex_policies.yaml"
        yaml_file.write_text(yaml_content)
        
        policies = load_policies_from_yaml(str(yaml_file))
        
        assert len(policies) == 1
        policy = policies[0]
        
        # Test the AND condition
        assert policy.evaluate({"cpu_percent": 90, "memory_percent": 90}) is True
        assert policy.evaluate({"cpu_percent": 90, "memory_percent": 80}) is False


class TestPolicyIntegration:
    """Integration tests for policy engine with other components"""
    
    @pytest.mark.asyncio
    async def test_policy_evaluation_flow(self):
        """Test complete policy evaluation flow"""
        # This would test: metric → policy evaluation → action trigger → queue → worker
        # For now, we test the policy evaluation part
        
        registry = get_policy_registry()
        
        # Clear registry
        for policy_name in list(registry._policies.keys()):
            registry.unregister(policy_name)
        
        # Register test policy
        policy = Policy(
            name="integration-test-policy",
            description="Integration test",
            condition=all_conditions(
                metric_exceeds("cpu_percent", 80),
                metric_exceeds("memory_percent", 75)
            ),
            action=ActionType.RESTART_SERVICE,
            severity=Severity.CRITICAL,
            target="test-service",
            enabled=True,
            auto_remediate=False,  # Disable to avoid side effects
        )
        registry.register(policy)
        
        # Simulate metrics that trigger the policy
        metrics = {
            "cpu_percent": 85,
            "memory_percent": 80,
            "disk_usage_percent": 50,
        }
        
        result = await evaluate_policies(metrics, target="test-service")
        
        # Verify violation was detected
        assert len(result["violations"]) == 1
        violation = result["violations"][0]
        assert violation["policy_name"] == "integration-test-policy"
        assert violation["severity"] == "critical"
        assert violation["target"] == "test-service"
    
    @pytest.mark.asyncio
    async def test_policy_with_custom_action(self):
        """Test policy with custom action function"""
        call_count = []
        
        async def custom_action(target, params):
            call_count.append(1)
            return {
                "action": "custom",
                "target": target,
                "status": "success",
                "params": params,
            }
        
        registry = get_policy_registry()
        
        # Clear registry
        for policy_name in list(registry._policies.keys()):
            registry.unregister(policy_name)
        
        policy = Policy(
            name="custom-action-policy",
            condition=metric_exceeds("error_rate", 5),
            action=custom_action,
            severity=Severity.WARNING,
            enabled=True,
            auto_remediate=True,
        )
        registry.register(policy)
        
        result = await evaluate_policies({"error_rate": 10})
        
        # Custom action should have been called
        assert len(call_count) == 1
        assert len(result["actions_triggered"]) == 1
        assert result["actions_triggered"][0]["action"] == "custom"
