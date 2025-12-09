
#!/bin/bash

# Détecter le préfixe de Homebrew
if [ -d "/opt/homebrew" ]; then
    BREW_PREFIX="/opt/homebrew"
else
    BREW_PREFIX="/usr/local"
fi

echo "Utilisation du préfixe Homebrew : $BREW_PREFIX"
export DYLD_LIBRARY_PATH="$BREW_PREFIX/lib:$DYLD_LIBRARY_PATH"

# Supprimer l'ancienne application (sauf la base de données)
echo "Suppression des anciens fichiers Python et caches..."
find . -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete
find . -type d -name '__pycache__' -exec rm -rf {} +
find . -type f -name '*.py' ! -name 'app.py' ! -name 'schema.sql' ! -name 'requirements.txt' ! -name 'start.sh' ! -name '*.db' -delete

# Recompiler (rien à compiler en Python, mais on peut forcer un nettoyage)
echo "Nettoyage terminé."


# Supprimer l'environnement virtuel existant s'il est corrompu
if [ -d "venv" ]; then
    echo "Suppression de l'ancien environnement virtuel..."
    rm -rf venv
fi

# Créer un nouvel environnement virtuel
echo "Création de l'environnement virtuel..."
"$BREW_PREFIX/bin/python3" -m venv venv

# Activer l'environnement virtuel
source venv/bin/activate

# Installer ou mettre à jour les dépendances
echo "Installation des dépendances..."
pip install -q -r requirements.txt

# Lancer l'application directement avec Python dans l'environnement virtuel
echo "Lancement de l'application sur http://localhost:5001"
echo "Appuyez sur CTRL+C pour arrêter..."
python app.py
