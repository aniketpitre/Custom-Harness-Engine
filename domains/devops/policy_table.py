from core.primitives.policy import RiskTier


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
