"""
Fix predictor SQL query: NASY_APP → FRST
"""
with open('risk_predictor/risk_predictor.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Fix the query
content = content.replace("applicant_type = 'NASY_APP'", "applicant_type = 'FRST'")

with open('risk_predictor/risk_predictor.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("✅ Fixed predictor SQL query!")
print("   NASY_APP → FRST")
print("\nRestart predictor:")
print("   docker-compose restart risk_predictor")
