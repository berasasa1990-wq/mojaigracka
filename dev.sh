# Source from the MojaIgracka project root: source ./dev.sh
if [ ! -f ./OnlineShopProject/settings.py ] || [ ! -f ./venv/bin/activate ]; then
    echo "Pokreni source ./dev.sh iz foldera MojaIgracka." >&2
    return 1
fi
. ./venv/bin/activate
export DJANGO_ENV=development
export DEBUG=true
# Local development uses this project's SQLite database only.
unset DATABASE_URL
python -c 'import sys; print("MojaIgracka Python:", sys.executable)'
