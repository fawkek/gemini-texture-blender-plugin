## Demo

[Watch demo video](assets/demo.mp4)

# Gemini Texture Generator for Blender

Blender add-on that:

- calls the Gemini image API from a panel inside Blender
- lets you enter a prompt
- stores the API key in Add-on Preferences
- opens the Google AI Studio API key page from a button
- has a clearly labeled free model preset and a protected paid model preset
- supports `Seamless`, `Free`, and fixed `1024x1024` generation modes
- shows a preview of the generated texture
- generates helper `Normal`, `Roughness`, and `Metallic` maps
- applies the texture to selected faces or the active object
- has `Apply + Create UV If Missing`
- uses `BOX` projection plus `Cube Projection`
- can resize the generated texture to `512`, `256`, or `128`
- saves generated textures and maps to a local output folder

## Important

The plugin defaults to `FREE - Gemini 2.0 Flash Image` (`gemini-2.0-flash-preview-image-generation`) when that model is available for your Google AI Studio project.

`PAID - Gemini 2.5 Flash Image / Nano Banana` (`gemini-2.5-flash-image`) can charge your billing account. The plugin requires an extra confirmation checkbox before using this paid model.

Free quotas, model availability, and billing requirements are controlled by Google AI Studio / Gemini API and can differ by account, region, project, and current Google policy.

## Install

1. In Blender open `Edit > Preferences > Add-ons > Install...`
2. Select the `gemini_texture_generator` folder after zipping it, or package it as a zip first.
3. Enable the add-on.

## Use

1. Open `View3D > Sidebar > Gemini Tex`.
2. Open add-on settings in `Edit > Preferences > Add-ons`, find this add-on, and enter the Gemini API key there.
3. Optionally use the `Get API Key` button in Add-on Preferences.
4. Enter the prompt for the texture in the sidebar panel.
5. Choose the model preset. Use `FREE - Gemini 2.0 Flash Image` unless you intentionally want the paid Nano Banana model.
6. Enable `Seamless` if needed.
7. Choose `1024x1024` or `Free`.
8. Click `Generate Texture`.
9. Review the preview.
10. Click `Generate Maps` if you want helper normal, roughness, and metallic textures.
11. Click `Apply To Selection/Object` or `Apply + Create UV If Missing`.
12. Use `512`, `256`, or `128` to resize the current generated image set.
13. Use `Save Locally` to save the texture set to the configured output folder.

## Notes

- Default model preset is `FREE - Gemini 2.0 Flash Image`.
- The paid `gemini-2.5-flash-image` preset is protected by an extra confirmation checkbox.
- If you change the model to a Gemini 3 image model, the add-on also exposes the `1K/2K/4K` quality selector in `Free` mode.
- Helper maps are generated locally inside Blender from the base texture, so they do not require extra Gemini requests.
- If the current `.blend` file is saved, output files are stored in `Textures` next to the `.blend` file.
- If the current `.blend` file has not been saved yet, the add-on falls back to `~/BlenderGeminiTextures` or the folder set in Add-on Preferences.
- Gemini image generation capabilities and model names are documented at: https://ai.google.dev/gemini-api/docs/image-generation
