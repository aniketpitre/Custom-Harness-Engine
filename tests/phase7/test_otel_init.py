#!/usr/bin/env python3
"""
Test script to verify OpenTelemetry initialization works
"""
import sys
import os

# Add the project root to the Python path
sys.path.insert(0, '/workspaces/Custom-Harness-Engine')

# Set up Vault environment for the test
os.environ["VAULT_ADDR"] = "http://127.0.0.1:8200"
os.environ["VAULT_TOKEN"] = "c6869775842d732f69f590ac45ec422847ca27ffa15a9bf9b45719437a6803f4"
os.environ["VAULT_MOUNT_POINT"] = "harness-secrets"

# Set up OpenTelemetry endpoint (using localhost for testing)
os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = "http://localhost:4317"

def test_opentelemetry_init():
    """Test that OpenTelemetry tracing initializes correctly"""
    try:
        from core.agent_engine import tracer
        from opentelemetry import trace
        
        # Test that we have a tracer
        assert tracer is not None, "Tracer should not be None"
        
        # Test that we can create a span
        with tracer.start_as_current_span("test_span") as span:
            span.set_attribute("test.attribute", "test_value")
            span.add_event("test_event")
        
        print("✅ OpenTelemetry initialization test passed")
        return True
        
    except Exception as e:
        print(f"❌ OpenTelemetry initialization test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_opentelemetry_init()
    if success:
        print("\nOpenTelemetry initialization test completed successfully!")
        sys.exit(0)
    else:
        print("\nOpenTelemetry initialization test failed!")
        sys.exit(1)