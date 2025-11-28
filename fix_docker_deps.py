"""
Fix docker-compose dependencies pour scheduler
"""
with open('docker-compose.yml', 'r', encoding='utf-8') as f:
    content = f.read()

# Fix predictor dependency
content = content.replace(
    'condition: service_completed_successfully',
    'condition: service_healthy'
)

with open('docker-compose.yml', 'w', encoding='utf-8') as f:
    f.write(content)

print("✅ Fixed docker-compose dependencies")
print("   Changed: service_completed_successfully → service_healthy")
print("\nAll services can now start with scheduler running")
