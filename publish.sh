#!/bin/bash
# Memory Share 打包发布脚本

set -e

echo "🧹 Cleaning old builds..."
rm -rf dist/ build/ *.egg-info src/*.egg-info

echo "📦 Building package..."
python3 -m build

echo "✅ Checking package..."
python3 -m twine check dist/* 2>/dev/null || echo "⚠️  twine not installed, skipping check"

echo ""
echo "📁 Build complete! Files in dist/:"
ls -lh dist/

echo ""
echo "📋 Next steps:"
echo ""
echo "1. Test installation:"
echo "   pip install dist/memory-share-*.whl"
echo ""
echo "2. Publish to Test PyPI:"
echo "   twine upload --repository testpypi dist/*"
echo ""
echo "3. Publish to PyPI:"
echo "   twine upload dist/*"
echo ""
echo "4. Or distribute files manually from dist/ directory"
