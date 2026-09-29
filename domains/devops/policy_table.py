from core.primitives.policy import RiskTier

# Base tier per (tool, action). Argument-aware adjustments (protected namespaces, production
# apps) live in domains/devops/plugin.py and can only raise a tier, never lower it.
TOOL_RISK_TABLE = {
    ("filesystem", "read_directory"): RiskTier.R0,
    ("kubectl", "get"): RiskTier.R0,
    ("kubectl", "describe"): RiskTier.R0,
    ("kubectl", "logs"): RiskTier.R0,
    ("argocd", "app_list"): RiskTier.R0,
    ("argocd", "app_get"): RiskTier.R0,
    ("kubectl", "restart_pod"): RiskTier.R2,
    ("argocd", "app_sync_staging"): RiskTier.R2,
    ("argocd", "app_sync_production"): RiskTier.R3,
    ("gitops", "propose_change"): RiskTier.R2,
    ("kubectl", "delete_namespace"): RiskTier.R4,
    ("terraform", "destroy"): RiskTier.R4,
}
