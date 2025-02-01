# Pokémon Switch Animation Blender Importer/Exporter

This is Blender 2.80+ addon for importing single or multiple animation files from the Pokémon games in Nintendo Switch (Pokémon Sword/Shield, Let's GO Pikachu/Eevee, Legends Arceus and Scarlet/Violet).
## Dependencies:
- [Flatbuffers library](https://pypi.org/project/flatbuffers/) (the addon will attempt installing it using pip if not detected)
## Implemented:
- Animation import:
  - Translation transforms
  - Scaling transforms (requires correct "Inherit Scale" option to be set on bones prior to importing animation)
  - Rotation transforms
- Animation export:
  - Translation transforms
  - Scaling transforms ("Inherit Scale" option is not taken into account as it's part of armature, not animation)
  - Rotation transforms
## Not implemented:
- Material flags
- Event data

As of now import speed is much lower than export due to using `use_local_location` workaround, which requires updating scene for every bone transformed.

Flatbuffers schema scripts were generated from [pkZukan's gfbanm.fbs](https://github.com/pkZukan/PokeDocs/blob/main/SWSH/Flatbuffers/Animation/gfbanm.fbs).

If you need addon for importing and/or exporting both animations and meshes, download [this one](https://github.com/ChicoEevee/Pokemon-Switch-V2-Model-Importer-Blender). It fully includes this addon, but may occasionally be out-of-date.