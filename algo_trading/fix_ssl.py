"""
fix_ssl.py - Windows SSL Certificate Fix
Ek baar chalao, phir main.py kaam karega

Run: python fix_ssl.py
"""
import subprocess
import sys
import os

print("🔧 SSL Certificate Fix for Windows")
print("-" * 40)

# Step 1: certifi install/upgrade
print("\n[1/3] Installing/upgrading certifi...")
subprocess.run([sys.executable, "-m", "pip", "install", "--upgrade", "certifi"], check=True)

# Step 2: pip certificates update
print("\n[2/3] Updating pip certificates...")
try:
    import certifi
    cert_path = certifi.where()
    print(f"  Certificate path: {cert_path}")
    os.environ["SSL_CERT_FILE"] = cert_path
    os.environ["REQUESTS_CA_BUNDLE"] = cert_path
    print("  ✅ Environment variables set")
except Exception as e:
    print(f"  ⚠️  {e}")

# Step 3: Test SSL connection
print("\n[3/3] Testing SSL connection to Kite API...")
try:
    import requests
    import certifi
    response = requests.get(
        "https://api.kite.trade",
        verify=certifi.where(),
        timeout=10
    )
    print(f"  ✅ SSL connection successful! Status: {response.status_code}")
except requests.exceptions.SSLError as e:
    print(f"  ❌ Still SSL error: {e}")
    print("\n  Trying alternate fix...")
    # Windows certificate store se fix
    try:
        subprocess.run([
            sys.executable, "-m", "pip", "install",
            "pip-system-certs", "--prefer-binary"
        ], check=True)
        print("  ✅ pip-system-certs installed - restart terminal aur try karo")
    except Exception:
        pass
except Exception as e:
    print(f"  Response: {e}")

print("\n" + "="*40)
print("✅ Done! Ab chalao: python main.py")
print("="*40)
