#!/usr/bin/env python3
"""
Test script to verify ArgoCD tools work
"""
import os

# Set up Vault environment
os.environ["VAULT_ADDR"] = "http://127.0.0.1:8200"
os.environ["VAULT_TOKEN"] = "c6869775842d732f69f590ac45ec422847ca27ffa15a9bf9b45719437a6803f4"
os.environ["VAULT_MOUNT_POINT"] = "harness-secrets"

from domains.devops.tools.argocd_tools import argocd_app_list

def test_argocd_tools():
    """Test that we can use ArgoCD tools"""
    print("Testing ArgoCD app list...")
    try:
        result = argocd_app_list()
        print(f"ArgoCD app list result: {result}")
        return True
    except Exception as e:
        print(f"Error testing ArgoCD tools: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_argocd_tools()
    if success:
        print("\nArgoCD test completed successfully!")
    else:
        print("\nArgoCD test failed!")
        exit(1)