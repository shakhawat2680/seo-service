import secrets
import hashlib
from typing import Optional, Dict
from datetime import datetime
from models import execute_query, get_tenant_by_api_key, check_rate_limit, increment_usage, log_usage

def generate_api_key() -> str:
    """Generate a secure API key"""
    return f"aseo_{secrets.token_urlsafe(32)}"

def hash_api_key(api_key: str) -> str:
    """Hash API key for storage"""
    return hashlib.sha256(api_key.encode()).hexdigest()

def verify_api_key(api_key: str) -> Optional[Dict]:
    """Verify API key and return tenant info with rate limit check"""
    if not api_key or not api_key.startswith('aseo_'):
        return None
    
    # Hash the provided key
    key_hash = hash_api_key(api_key)
    
    # Get tenant
    tenant = get_tenant_by_api_key(key_hash)
    
    if not tenant:
        return None
    
    # Check rate limit
    if not check_rate_limit(tenant['id']):
        return {
            'error': 'rate_limit_exceeded',
            'message': 'Rate limit exceeded. Please upgrade your plan or try again later.',
            'tenant': tenant
        }
    
    # Log usage
    log_usage(tenant['id'], 'api_call', 'authentication')
    increment_usage(tenant['id'])
    
    return tenant

def create_api_key_for_tenant(tenant_id: str) -> str:
    """Create new API key for tenant"""
    api_key = generate_api_key()
    key_hash = hash_api_key(api_key)
    
    execute_query(
        "UPDATE tenants SET api_key = ?, updated_at = ? WHERE id = ?",
        (key_hash, datetime.now().isoformat(), tenant_id)
    )
    
    return api_key
