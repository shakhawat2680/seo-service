import secrets
import hashlib
from typing import Optional, Dict
from models import execute_query

def generate_api_key() -> str:
    """Generate a secure API key"""
    return f"aseo_{secrets.token_urlsafe(32)}"

def hash_api_key(api_key: str) -> str:
    """Hash API key for storage"""
    return hashlib.sha256(api_key.encode()).hexdigest()

def verify_api_key(api_key: str) -> Optional[Dict]:
    """Verify API key and return tenant info"""
    if not api_key or not api_key.startswith('aseo_'):
        return None
    
    # Hash the provided key
    key_hash = hash_api_key(api_key)
    
    # Look up in database
    results = execute_query(
        "SELECT id, name, email FROM tenants WHERE api_key = ?",
        (key_hash,),
        fetch=True
    )
    
    if results:
        return {
            'id': results[0][0],
            'name': results[0][1],
            'email': results[0][2]
        }
    return None

def create_api_key_for_tenant(tenant_id: str) -> str:
    """Create new API key for tenant"""
    api_key = generate_api_key()
    key_hash = hash_api_key(api_key)
    
    execute_query(
        "UPDATE tenants SET api_key = ? WHERE id = ?",
        (key_hash, tenant_id)
    )
    
    return api_key
