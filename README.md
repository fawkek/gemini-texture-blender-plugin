## Demo

[Watch demo video](assets/demo.mp4)

# Gemini Texture Generator for Blender

Blender add-on that:

- calls the Gemini image API from a panel inside Blender
- lets you enter a prompt
- stores the API key in Add-on Preferences
- opens the Google AI Studio API key page from a button
- supports `Seamless`, `Free`, and fixed `1024x1024` generation modes
- shows a preview of the generated texture
- generates helper `Normal`, `Roughness`, and `Metallic` maps
- applies the texture to selected faces or the active object
- has `Apply + Create UV If Missing`
- uses `BOX` projection plus `Cube Projection`
- can resize the generated texture to `512`, `256`, or `128`
- saves generated textures and maps to a local output folder

## Important

For the plugin to work with the Gemini image API, your Google AI Studio / Gemini API project may require billing to be enabled and a payment card linked, depending on the model and quota tier available to your account.

## Install

1. In Blender open `Edit > Preferences > Add-ons > Install...`
2. Select the `gemini_texture_generator` folder after zipping it, or package it as a zip first.
3. Enable the add-on.

## Use

1. Open `View3D > Sidebar > Gemini Tex`.
2. Open add-on settings in `Edit > Preferences > Add-ons`, find this add-on, and enter the Gemini API key there.
3. Optionally use the `Get API Key` button in Add-on Preferences.
4. Enter the prompt for the texture in the sidebar panel.
5. Enable `Seamless` if needed.
6. Choose `1024x1024` or `Free`.
7. Click `Generate Texture`.
8. Review the preview.
9. Click `Generate Maps` if you want helper normal, roughness, and metallic textures.
10. Click `Apply To Selection/Object` or `Apply + Create UV If Missing`.
11. Use `512`, `256`, or `128` to resize the current generated image set.
12. Use `Save Locally` to save the texture set to the configured output folder.

## Notes

- Default model is `gemini-2.5-flash-image`.
- If you change the model to a Gemini 3 image model, the add-on also exposes the `1K/2K/4K` quality selector in `Free` mode.
- Helper maps are generated locally inside Blender from the base texture, so they do not require extra Gemini requests.
- If the current `.blend` file is saved, output files are stored in `Textures` next to the `.blend` file.
- If the current `.blend` file has not been saved yet, the add-on falls back to `~/BlenderGeminiTextures` or the folder set in Add-on Preferences.
- Gemini image generation capabilities and model names are documented at: https://ai.google.dev/gemini-api/docs/image-generation
