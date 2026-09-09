# GameTrack

Tracker local Windows avec dashboard web, détection de processus et ajout de jeux personnalisés.

## Compilation

Sur Windows avec Python 3.10+ :

1. Double-cliquer `build.bat`.
2. Laisser l'installation se terminer.
3. L'EXE sera dans `dist\GameTrack.exe`.

## Ajouter un jeu personnalisé

1. Ouvrir GameTrack.
2. Cliquer **+ Ajouter un jeu**.
3. Lancer le jeu.
4. Cliquer **J'ai lancé le jeu**.
5. Sélectionner le processus `.exe` correspondant.
6. Donner un nom au jeu.
7. Cliquer **Ajouter au tracker**.

Le tracker surveille ensuite ce processus et crée une session automatiquement quand il est ouvert puis fermé.

Les données sont stockées localement dans `%APPDATA%\GameTrack\gametrack.db`.

