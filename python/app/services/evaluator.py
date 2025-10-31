import os
import glob
import yaml
import time
from typing import List, Dict, Any

POLICY_DIR = "manifests/policies/"
POLICIES: List[Dict[str, Any]] = []
POLICY_COOLDOWNS: Dict[str, float] = {}  # {policy_name: last_trigger_timestamp}


def load_policies():
    """
    Finds and loads all policy YAMLs from the manifest directory.
    This function will overwrite the global POLICIES list.
    """
    global POLICIES
    POLICIES = []

    # Find all .yaml and .yml files
    policy_files = glob.glob(os.path.join(POLICY_DIR, "*.yaml"))
    policy_files.extend(glob.glob(os.path.join(POLICY_DIR, "*.yml")))

    for f_path in policy_files:
        try:
            with open(f_path, 'r') as f:
                # Use safe_load_all to support multi-document YAMLs
                for policy in yaml.safe_load_all(f):
                    if policy and isinstance(policy, dict) and policy.get("name"):
                        POLICIES.append(policy)
        except Exception:
            # Silently fail on parse/read error as per "no logs"
            pass


def evaluate_policies(name: str, value: float) -> List[Dict[str, str]]:
    """
    Evaluates a metric against all loaded policies and returns
    a list of triggered actions that are not on cooldown.
    """
    triggered_actions = []
    now = time.time()

    for policy in POLICIES:
        try:
            # Check for minimum required policy fields
            required_keys = ["name", "match_metric", "threshold", "action", "target"]
            if not all(k in policy for k in required_keys):
                continue

            policy_name = policy["name"]

            # 1. Check metric name
            if policy["match_metric"] != name:
                continue

            # 2. Check threshold (assuming trigger is value > threshold)
            if value <= float(policy["threshold"]):
                continue

            # 3. Check cooldown
            # Default to 300s (5 min) if cooldown is not specified
            cooldown_seconds = int(policy.get("cooldown", 300))
            last_triggered = POLICY_COOLDOWNS.get(policy_name, 0.0)

            if (now - last_triggered) < cooldown_seconds:
                continue  # Still on cooldown

            # All checks passed: Trigger
            POLICY_COOLDOWNS[policy_name] = now

            triggered_actions.append({
                "target": policy["target"],
                "action": policy["action"],
                "policy": policy_name
            })

        except (ValueError, TypeError, KeyError):
            # Silently fail on malformed policy (e.g., non-numeric threshold)
            pass

    return triggered_actions


# --- Load policies on module import ---
load_policies()
