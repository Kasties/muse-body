# Muse Jolly → VRChat

Files in this folder:
- `Muse_Jolly.fbx`: skinned mesh (13,312 tris) + humanoid armature (19 bones, including `Chest` and the shoulders VRChat requires) + shape keys `Blink` and `MouthOpen`
- `Muse_BaseColor.png`: baked colours (fur, face, blush, mouth), 2048×2048
- `Fur/`: the fur shader, its two textures and the `Muse_Fur` material. Copy it into the Unity project as `Assets/muse/Fur`.
- `Fur_Preview.png`: a test render of the fur

Performance: 13,312 tris and 2 material slots is **Excellent** on PC (up to 32,000 tris and 4 slots) and **Medium** on Quest/Android (up to 15,000 tris and 2 slots). Quest players only see Medium or better by default, so don't add materials or meshes for the Quest version.

## 1. Open the avatar project
Use the **VRChat Creator Companion**. Muse was built in an Avatar project with Avatars SDK 3.10.6 and Unity 2022.3.22f1 (with Android support for a Quest version).
You can also create a new **Avatar** project in VCC. If VCC wants a newer SDK or Unity version, let it update.

## 2. Import
1. In Unity's **Project** window, create a folder `Assets/Muse`.
2. Drag `Muse_Jolly.fbx` and `Muse_BaseColor.png` into it.

## 3. FBX import settings (click `Muse_Jolly.fbx`, look at the Inspector)
- **Model** tab: tick **Read/Write** (the SDK won't upload without it) and leave **Scale Factor 1**, then click **Apply**.
- **Rig** tab:
  1. Set **Animation Type: Humanoid** and **Avatar Definition: Create From This Model**, then click **Apply**.
  2. Click **Configure…**. Unity's automatic mapping leaves **Chest**, **Left Shoulder** and **Right Shoulder** empty, and VRChat won't build without them. Drag `Chest`, `LeftShoulder` and `RightShoulder` from the Hierarchy into their empty circles. Every body bone should then be green: Hips, Spine, Chest, Neck, Head, both shoulders, and the upper arm, lower arm, hand, upper leg, lower leg and foot bones.
  3. The arms hang down in the file. In Configure, choose **Pose → Enforce T-Pose**, then **Done**.
- **Materials** tab: click **Extract Materials…** and pick `Assets/Muse`. That gives you editable `Muse_Body` and `Muse_Eyes` materials.

## 4. Put it in the scene
1. Drag the FBX into the **Hierarchy** and set Position 0,0,0.
2. Check it faces **+Z**, the blue arrow. If it faces backwards, rotate the root by 180° on Y.
3. The `Muse_Armature` child may show an X rotation of about -90. That's normal for Blender exports, so leave it.

## 5. Shaders
| Material | PC | Quest/Android |
|---|---|---|
| `Muse_Body` | Poiyomi Toon (free) or Standard, Albedo = `Muse_BaseColor`. For fur, use `Muse_Fur` instead (see Fur) | VRChat/Mobile/Toon Lit, Texture = `Muse_BaseColor` |
| `Muse_Eyes` | Standard, black, Smoothness 0.9 (glossy beads) | VRChat/Mobile/Standard Lite, black |

## 6. VRC Avatar Descriptor
Select the root `Muse_Jolly` object, then **Add Component → VRC Avatar Descriptor**.
- **View → View Position:** put the ball between the eyes, level with the front of the beads: **X 0, Y 1.54, Z 0.40**. Click **Edit** if you want to drag it.
- **LipSync:**
  - **Mode:** **Jaw Flap Blend Shape**
  - **Face Mesh:** `Muse`
  - **Jaw Flap Blend Shape:** `MouthOpen`
- **Eye Look:** enable it.
  - **Eyelids:** **Blendshapes**, mesh `Muse`, **Blink** = `Blink`. The others can stay `-none-`.
  - **Eye bones:** leave them empty. The eyes are beads, so blinking is all they need.

## 7. Test and upload
1. Open **VRChat SDK → Show Control Panel** and log in.
2. Your account must be allowed to upload avatars (New User trust rank or higher).
3. In the **Builder** tab, fix anything listed. **Auto Fix** handles most issues.
4. Give it a name and thumbnail. Click **Build & Test** to try it locally first, then **Build and Publish**.

For a Quest version, switch the Builder to **Android**, use the Mobile shaders from step 5, and publish again to the same avatar.

## Fur (PC)
Blender's particle fur can't go to VRChat. Instead, `Fur/` (copied to `Assets/muse/Fur`) has a shell-fur shader made for Muse, `Muse/Fur`, adapted from Sorumi's UnityFurShader. It comes with a ready material, `Muse_Fur`.
1. In the Hierarchy, expand your avatar and select `Muse`.
2. In **Skinned Mesh Renderer → Materials**, drag `Muse_Fur` onto **Element 0**, replacing `Muse_Body`.
3. Check it in the Scene view, then use **Build & Test**.

The face stays bare because of `Muse_FurMask` (white = fur), which was baked from the `Face` vertex group in Blender.

| `Muse_Fur` setting | What it does |
|---|---|
| Fur Length | Length in metres (0.045 = 4.5 cm) |
| Hair Count | Higher = more, finer hairs |
| Tip Thinning | Higher = hairs taper off sooner |
| Fur Opacity | How solid the fur looks |
| Root Shadow | Darkening deep between the hairs |
| Gravity | How much the tips droop, as a world direction (negative Y = down) |
| Soft Lighting | Lets light wrap further around the fur |
| Rim Sheen / Rim Width | Soft glow along the outline |

Good to know:
- The shader draws Muse 17 times: 1 solid layer plus 16 fur layers. VRChat's performance rank ignores shaders, so it still says Excellent, but it costs more than the plain material.
- People who block custom shaders see the plain colour texture.
- Sunlight, light probes and ambient light light the fur. Realtime point and spot lights don't.
- Quest can't use custom shaders. For the Android version, duplicate the avatar (Ctrl+D), give the copy `Muse_Body` with VRChat/Mobile/Toon Lit, and upload the copy from the Android build target. It keeps the same avatar ID.

## Changing the size
Muse is about 2 m tall. To change that, select the root `Muse_Jolly` and set all three **Scale** values of its Transform to the same number. The View Position doesn't follow the scale, so multiply its Y and Z by that number too.

| Scale | Height | View Position (X, Y, Z) |
|---|---|---|
| 0.9 | 1.8 m | 0, 1.39, 0.36 |
| 0.85 | 1.7 m | 0, 1.31, 0.34 |
| 0.8 | 1.6 m | 0, 1.23, 0.32 |

At 0.85 and below, the Builder warns that the avatar is shorter than average. It's only a warning.

## Updating the model
Keep modeling the original objects in `Muse_Jolly_Reference.blend`. The **VRChat Export** collection is a generated copy.
After changes, rebuild the export: delete the collection and ask to regenerate it, or redo the steps. Then re-import the FBX in Unity. The Avatar Descriptor settings stay.
A rebuilt export gets a new UV layout, so `Muse_BaseColor` and `Muse_FurMask` must be re-baked with it.
If the bones change, open **Rig → Configure…** again and check that all 19 are green.

## Build errors
- **Spine hierarchy missing elements, please map: Shoulders, Chest.** The humanoid mapping is missing those bones. Map them as in step 3.
- **Loaded data for an avatar we do not own, clearing blueprint ID.** Harmless. The SDK drops an avatar ID that doesn't belong to your account, and your first upload creates a new one.
