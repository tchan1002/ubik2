#!/bin/bash
# Safety verification before pushing to public repo

echo "🔒 Git Safety Verification"
echo "=========================="
echo ""

# Check if git is initialized
if [ ! -d .git ]; then
    echo "❌ Git not initialized. Run: git init"
    exit 1
fi

echo "✓ Git initialized"
echo ""

# Stage all files
git add . 2>/dev/null

echo "📋 Checking for sensitive data..."
echo ""

SENSITIVE_FILES=(
    "docs/data.json"
    "*.vcf"
    "contact_names.json"
    "*.db"
    "test_*.py"
    "debug_*.py"
    "*contact*.json"
)

FOUND_SENSITIVE=0

for pattern in "${SENSITIVE_FILES[@]}"; do
    # Check if any files matching pattern are staged
    if git diff --cached --name-only | grep -q "$pattern"; then
        echo "❌ DANGER: Found staged file matching: $pattern"
        git diff --cached --name-only | grep "$pattern"
        FOUND_SENSITIVE=1
    fi
done

# Check specifically for docs/data.json
if git ls-files | grep -q "docs/data.json"; then
    echo "❌ DANGER: docs/data.json is tracked by git!"
    FOUND_SENSITIVE=1
fi

# Check for phone numbers in staged files
echo ""
echo "🔍 Scanning for phone numbers in staged Python files..."
PHONE_PATTERN='(\+1|1)?[- .]?\(?[0-9]{3}\)?[- .]?[0-9]{3}[- .]?[0-9]{4}'

for file in $(git diff --cached --name-only | grep "\.py$"); do
    if [ -f "$file" ]; then
        if grep -qE "$PHONE_PATTERN" "$file"; then
            echo "⚠️  Warning: Possible phone number in: $file"
            grep -n -E "$PHONE_PATTERN" "$file" | head -3
        fi
    fi
done

echo ""
echo "📊 Files to be committed:"
echo "------------------------"
git diff --cached --name-only
echo ""

if [ $FOUND_SENSITIVE -eq 1 ]; then
    echo ""
    echo "❌ UNSAFE TO PUSH - Sensitive data detected!"
    echo "   Fix issues above before committing"
    exit 1
else
    echo ""
    echo "✅ No obvious sensitive data detected"
    echo ""
    echo "⚠️  FINAL CHECKLIST:"
    echo "  [ ] docs/data.json is NOT in the list above"
    echo "  [ ] No .vcf files in the list"
    echo "  [ ] No test_*.py or debug_*.py files"
    echo "  [ ] You've reviewed the file list carefully"
    echo ""
    echo "If all checked, you can safely commit and push!"
fi
