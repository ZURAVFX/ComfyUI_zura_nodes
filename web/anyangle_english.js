import { app } from "../../scripts/app.js";

// Presentation-only compatibility layer for T8 AnyAngle Studio 1.5.7.
// Keep upstream installed separately. Never translate scene data, form values,
// prompt previews, saved names, model paths, or postMessage/API payloads.
const TEXT = new Map(Object.entries({
  "工作台版本": "Studio version", "相机工作台": "Camera studio",
  "撤销 Ctrl+Z": "Undo Ctrl+Z", "重做 Ctrl+Shift+Z": "Redo Ctrl+Shift+Z",
  "撤销": "Undo", "重做": "Redo", "取消": "Cancel", "关闭": "Close",
  "保存": "Save", "导入": "Import", "导出": "Export", "重载": "Reload",
  "应用到节点": "Apply to node", "保存场景": "Save scene",
  "原图": "Source image", "导入原图": "Import source image",
  "选择参考原图": "Choose source image", "完整参考原图": "Full source image",
  "导入参考原图": "Import source image", "姿势提取 / 3D 重建 / image_1": "Pose extraction / 3D reconstruction / image_1",
  "支持节点左侧 IMAGE 连线，也可上传原图。": "Use the connected IMAGE input, or upload a source image.",
  "读取上游图像": "1 · Read connected image", "保留背景参与重建": "Include background in reconstruction",
  "实验": "Experimental", "勾选后整张图参与三维重建；房间与大场景的效果取决于 TripoSplat。切换后需重新重建。": "Reconstruct the whole image. Rooms and large scenes depend on TripoSplat. Rebuild after changing this option.",
  "从原图重建 3D": "2 · Reconstruct 3D", "从原图重建对应主体，再调整机位。": "Reconstruct the source subject, then adjust the camera.",
  "导入 GLB": "Import GLB", "人偶": "Mannequin", "从原图复制姿势到人偶": "Copy source pose to mannequin",
  "正在载入场景": "Loading scene", "重建模型": "Reconstruction models", "本机选择": "Local selection",
  "自动识别模型子目录；已重命名的兼容权重可手动选择。设置保存在当前浏览器。": "Models are detected automatically. Select renamed compatible weights manually. Choices are saved in this browser.",
  "刷新列表": "Refresh list", "保存选择": "Save selection", "展开后读取本机模型列表。": "Expand to read the local model list.",
  "姿势库": "Pose library", "随机类型": "Pose category", "混合": "Mixed", "站姿": "Standing", "动作": "Action", "坐姿": "Seated",
  "随机姿势": "Random pose", "作用范围": "Apply to", "当前人物": "Current person", "选中人物": "Selected people", "全部未锁定人物": "All unlocked people",
  "种子": "Seed", "按种子重现": "Repeat seed", "有约束的动作变化，可继续手动调整、撤销或保存。": "Constrained pose variations. Adjust, undo or save the result.",
  "保存姿势": "Save pose", "导入本编辑器导出的姿势 JSON": "Import a pose JSON exported by this editor", "导出姿势 JSON": "Export pose JSON",
  "全场模板与便携场景": "Scene templates and transfer", "选择全场模板": "Choose a scene template", "保存全场": "Save full scene", "应用模板": "Apply template",
  "全场模板保存人物、道具、姿势与站位；应用后保留已有角色的身份绑定。机位收藏仍只保存相机。": "Scene templates save people, props, poses and positions while preserving identity bindings. Saved views store only the camera.",
  "导出场景 ZIP": "Export scene ZIP", "导入场景 ZIP": "Import scene ZIP", "ZIP 包含照片、三维资产和场景，可在另一台电脑恢复。": "The ZIP includes photos, 3D assets and scene settings for use on another computer.",
  "手势": "Hand poses", "人物自身左右": "Person's own left and right", "体型": "Body shape", "关节精调": "Joint adjustments", "未选择": "None selected",
  "切换“编辑场景”，点选关节或拖动 IK 手脚控制点。": "Choose Edit scene, then select joints or drag hand and foot controls.",
  "选择关节": "Select joint", "复位当前关节": "Reset selected joint", "场景与构图": "Scene and framing", "载入三维主体后可调整场景与构图。": "Load a 3D subject to adjust the scene and framing.",
  "重置机位": "Reset camera", "三维工作台": "3D studio", "工作画面": "Workspace view", "引导图预览": "Guide preview", "3D 工作台": "3D studio",
  "输出画幅": "Output aspect ratio", "自定义": "Custom", "交互 3D 场景：拖动改变机位，中键或 Shift 拖动平移，滚轮缩放": "Drag to orbit; middle-drag or Shift-drag to pan; scroll to zoom",
  "编辑模式": "Edit mode", "拍摄机位": "Camera", "人物站位": "People placement", "编辑场景": "Edit scene", "叠加原图校准": "Overlay source for alignment", "原图叠加": "Source overlay",
  "半透明原图校准": "Source alignment overlay", "原图重建姿势固定 · 仅可调整机位": "Reconstructed pose is fixed · adjust the camera",
  "将当前视图设为机位": "Use this view as camera", "将整个资产放入拍摄画幅": "Fit the full asset in frame", "适合画幅": "Fit in frame",
  "让原图成为三维场景": "Turn the source into a 3D scene", "连接参考图或上传图片": "Connect or upload a source image", "重建对应主体后，拖动相机探索新视角": "Reconstruct the subject, then drag to explore camera angles",
  "引导图": "Guide image", "实际输出 · image_2": "Actual output · image_2", "当前引导图的完整输出预览": "Full guide image preview", "请先生成引导图": "Generate a guide image first",
  "在右侧生成、导入或读取结构图": "Generate, import or read a guide on the right", "正在准备 3D 工作台": "Preparing 3D studio", "加载本地渲染资源": "Loading local renderer",
  "黄框为输出范围": "Yellow border marks the output", "拖动调整机位 · 中键或 Shift 平移 · 滚轮缩放": "Drag to orbit · middle-drag or Shift-drag to pan · scroll to zoom",
  "已保存机位": "Saved cameras", "批量机位": "Batch cameras", "收藏当前机位": "Save current camera",
  "把满意的机位留在这里。切换收藏只改变相机，姿势保持当前状态。": "Save favourite views here. Switching views changes the camera and keeps the current pose.",
  "引导策略": "Guidance", "生成模型": "Image model", "Qwen 底模": "Qwen base model", "引导图类型": "Guide type", "三维粗图": "3D render", "原图重建 / 场景": "Reconstruction / scene",
  "POSE 姿势": "Pose", "原图提取 / 导入": "Extract / import", "Depth 深度": "Depth", "原图估计 / 导入": "Estimate / import", "Canny 轮廓": "Canny edges", "原图生成 / 导入": "Generate / import",
  "预览当前机位粗图": "Preview camera guide", "TripoSplat 重建原图主体，再调整拍摄机位。": "Reconstruct the source with TripoSplat, then adjust the camera.",
  "直接输出原图的彩色骨架，保留原构图。可复制可见关节到人偶，画外肢体保持原姿势。": "Use the source pose and framing. Copy visible joints to a mannequin; off-screen limbs keep their pose.",
  "从原图提取姿势 · DWPose": "Extract source pose · DWPose", "导出全场骨架 JSON": "Export scene pose JSON", "输出手部关节": "Include hand joints", "真实手指骨架；人脸仅输出已知眼鼻点": "Finger joints; face uses known eye and nose points only",
  "骨架遮挡": "Pose occlusion", "全部已知关节": "All known joints", "仅未被人物 / 道具遮挡": "Only joints not hidden by people or props",
  "导入 OpenPose 图 / JSON": "Import OpenPose image / JSON", "读取连线骨架图": "Read connected pose", "姿势复制方式": "Pose transfer", "保守平面 · 可见关节": "Conservative 2D · visible joints", "推测立体 · 全身关节": "Estimated 3D · full body",
  "未生成骨架": "No pose generated", "使用原图骨架": "Use source pose", "用三维人偶调整姿势": "Edit pose with 3D mannequin",
  "正背翻转": "Flip front/back", "躯干前后": "Flip torso", "左上臂": "Left upper arm", "左小臂": "Left forearm", "右上臂": "Right upper arm", "右小臂": "Right forearm", "左大腿": "Left thigh", "左小腿": "Left calf", "右大腿": "Right thigh", "右小腿": "Right calf",
  "从原图估计深度 · DA3": "Estimate source depth · DA3", "从三维机位渲染深度": "Render camera depth", "深度反向 · 近黑远白": "Invert depth · near black, far white",
  "从原图生成 Canny": "Generate source Canny", "从三维机位生成 Canny": "Generate camera Canny", "导入结构图": "Import guide image", "读取连线结构图": "Read connected guide",
  "直接从原图估计深度，也可连接 Depth Anything 3 输出或导入 PNG。": "Estimate source depth, connect Depth Anything 3, or import a PNG.", "低阈值": "Low threshold", "高阈值": "High threshold",
  "同一场景的新机位粗图，配合 AnyAngle LoRA 使用。": "A guide of the same scene from a new angle, for the AnyAngle LoRA.",
  "拍摄相机": "Camera controls", "场景正面 · Y-UP · 透视": "Scene front · Y-up · perspective", "原图预测机位 · Y-UP · 透视": "Estimated source camera · Y-up · perspective",
  "镜头透视": "Lens perspective", "镜头": "Lens", "原始镜头 · 默认": "Original lens · default", "自定义焦距": "Custom focal length", "24 mm 广角": "24 mm wide", "50 mm 标准": "50 mm standard", "85 mm 长焦": "85 mm telephoto",
  "广角增强近大远小，长焦压缩空间。联动相机距离，尽量保持主体大小。": "Wide lenses exaggerate depth; long lenses compress it. Camera distance adjusts to maintain subject size.",
  "允许鼠标调整俯仰": "Allow vertical orbit", "关闭后仅水平旋转，俯仰滑条仍可使用": "Turn off for horizontal dragging only; the elevation slider still works",
  "预设视角": "Camera presets", "正面": "Front", "侧面": "Side", "背面": "Back", "原图机位": "Source camera", "回到原图机位": "Reset to source camera",
  "输出尺寸": "Output size", "宽度": "Width", "高度": "Height", "粗图背景": "Guide background", "粗图背景色": "Guide background colour", "实际粗渲染": "Camera guide output",
  "当前会输出到 image_2 的引导图": "Guide output to image_2", "只有画面内容会输出，网格与控制器不会进入粗图。": "Only the scene is exported. Grids and controls are excluded.",
  "导出当前引导图 PNG": "Export guide PNG", "接线与提示词": "Connections and prompt", "提示词模式": "Prompt mode", "双图模板 · 默认": "Two-image template · default", "仅引导图 · 无需原图": "Guide only · no source image",
  "自定义提示词": "Custom prompt", "图片顺序": "Image order", "原图 1 / 引导图 2": "Source 1 / guide 2", "引导图 1 / 原图 2": "Guide 1 / source 2", "原文输出，可留空后在工作流中拼接提示词": "Passed through unchanged. Leave empty to build the prompt in the workflow.",
  "附加描述": "Additional description", "描述人物、场景、服装和风格": "Describe the person, setting, clothing and style", "原图 → image_1；当前引导图 → image_2": "Source → image_1; guide → image_2",
  "保持原有双图模板，可调整图片编号并附加描述。": "Use the two-image template, with optional image reordering and additional description.",
  "LoRA 强度 → AnyAngle 模型加载器": "LoRA strength → AnyAngle model loader", "AnyAngle 模式下将 LoRA 强度接到加载器；底模模式自动输出 0。": "Connect LoRA strength to the loader. Base-model mode outputs 0.",
  "工作台性能": "Studio performance", "预览质量": "Preview quality", "流畅 · 1×": "Fast · 1×", "均衡 · 1.5×": "Balanced · 1.5×", "清晰 · 2×": "Sharp · 2×",
  "自动更新引导预览": "Update guide automatically", "卡顿时可关闭，改为手动刷新": "Turn off if slow, then refresh manually", "刷新引导图预览": "Refresh guide preview", "静止时按需重绘；预览质量不影响导出分辨率。": "Renders only when needed. Preview quality does not affect export resolution.",
  "准备中": "Preparing", "工作台资源加载失败": "Studio assets failed to load", "人偶应随节点安装，不需要 Fisher 插件。修复会校验并补齐人偶与贴图文件，不下载推理模型。": "The mannequin is included with T8. Repair checks mannequin assets and textures; it does not download inference models.",
  "修复人偶资源": "Repair mannequin assets", "重试加载": "Retry loading", "关闭工作台": "Close studio", "机位来源": "Camera source", "角度步进": "Angle range", "已收藏机位": "Saved cameras",
  "起始角度": "Start angle", "结束角度": "End angle", "步长": "Step", "批量渲染粗图": "Render guide batch", "批量生成最终图": "Generate final image batch",
  "0° → 360°、步长 1° 可生成 360 个机位。最终图沿用当前工作流的种子与采样设置，分别加入 ComfyUI 队列；请连接 Save Image 保存结果。从节点打开工作台才能批量生成最终图。": "A 0°–360° range at 1° steps creates 360 views. Final images use this workflow's seed and sampling settings and queue separately. Connect Save Image. Open Studio from the node to generate final images.",
  "选择机位范围，再开始批量。": "Choose an angle range, then start the batch.", "停止仅结束后续提交，已入队任务继续运行。": "Stop prevents further submissions. Already queued jobs continue.",
  "停止后续机位": "Stop further views", "下载粗图 ZIP": "Download guide ZIP", "下载任务清单": "Download job list", "命名": "Name",
  "从照片复制多人姿势": "Copy multiple poses from photo", "姿势来源原图": "Pose source photo", "新建人物时匹配原图左右站位并适合全场": "Match source positions and fit the full scene for new people",
  "同时将此照片绑定为身份参考": "Also use this photo as identity reference", "仅复制动作时可保持关闭": "Leave off to copy the pose only", "复制单人到当前人物": "Copy one pose to current person", "新建所选人物": "Create selected people",
  "方位角": "Orbit angle", "俯仰角": "Elevation", "构图缩放": "Framing zoom", "焦距": "Focal length", "年龄": "Age", "体型特征": "Body type", "体重": "Weight", "肌肉": "Muscle", "身高": "Height",
  "旋转 X": "Rotation X", "旋转 Y": "Rotation Y", "旋转 Z": "Rotation Z", "GLB 正面校准": "GLB front alignment", "资产尺度": "Asset scale", "构图水平偏移": "Horizontal framing", "构图垂直偏移": "Vertical framing", "左手": "Left hand", "右手": "Right hand", "放松": "Relaxed", "并拢": "Flat", "握拳": "Fist",
  "草稿有更改 · 应用后才会更新节点": "Unsaved camera changes · click Apply to node to save this view",
  "机位草稿 · 尚未应用": "Camera draft · click Apply to node to use this view",
  "尚未应用到节点": "Camera not applied · click Apply to node",
  "请先生成、导入或连接当前引导图": "Generate, import or connect the guide image first",
  "正在生成引导图预览…": "Generating guide preview…", "先从原图重建三维主体": "Reconstruct the source in 3D first", "请在右侧生成或导入引导图": "Generate or import a guide on the right",
  "三维工作台 · 调整机位与姿势": "3D studio · adjust camera and pose",
  "黄框为输出范围 · 拖动调整机位 · 中键或 Shift 平移 · 滚轮缩放": "Yellow border is the output · drag to orbit · middle/Shift-drag to pan · scroll to zoom",
  "原图重建主体与预测机位已对齐，姿势固定。请用拍摄相机调整角度、缩放和构图。": "Reconstruction is aligned to the source camera. The pose is fixed. Adjust angle, zoom and framing with the camera controls.",
  "连接原图并重建主体，或导入 GLB 后调整场景。": "Connect a source and reconstruct it, or import a GLB to adjust the scene.",
  "等待原图重建": "Waiting for reconstruction", "MakeHuman · 手动人偶": "MakeHuman · mannequin", "GLB 场景": "GLB scene", "TRIPOSPLAT · 保留背景": "TRIPOSPLAT · with background", "TRIPOSPLAT · 原图主体": "TRIPOSPLAT · source subject",
  "原图 3D 保持重建姿势，无可编辑骨架；拖动相机改变视角。需要手动摆姿可切换人偶。": "The reconstructed pose is fixed. Drag the camera to change view. Switch to a mannequin for pose editing.",
  "背景选项已改变 · 点击重建后应用；当前预览仍为上次结果。": "Background option changed · reconstruct again, then Apply to node. The preview still shows the previous result.",
  "按新设置重新重建 3D": "Reconstruct with new settings", "保留背景重建 3D": "Reconstruct with background", "重新载入原图 3D": "Rebuild source in 3D",
  "保留背景的三维重建已就绪，可预览或调整机位；大场景效果仍属实验。": "3D reconstruction with background is ready. Adjust the camera. Large scenes remain experimental.",
  "原图三维主体已就绪，可预览或调整新机位。": "Source reconstruction ready. Preview or adjust the camera.",
  "先从原图重建三维主体，再输出拍摄机位粗图。": "Reconstruct the source first, then render the camera guide.", "当前 GLB 场景可直接渲染粗图。": "The GLB scene is ready to render a guide.",
  "正在读取上游图像…": "Reading source frame…", "正在读取连线原图…": "Reading connected source…", "正在执行参考图的上游节点…": "Running source-image nodes…",
  "来自 IMAGE 连线 · 使用第一张图像": "Connected IMAGE · using the first frame", "点击读取上游图像，执行取得原图所需的节点": "Click Read connected image to run the input nodes",
  "正在读取本机模型列表…": "Reading local models…", "背景移除 · BiRefNet": "Background removal · BiRefNet", "图像编码 · DINOv3": "Image encoder · DINOv3", "三维重建 · TripoSplat": "3D reconstruction · TripoSplat", "图像 VAE · Flux2": "Image VAE · Flux2", "三维解码 · TripoSplat VAE": "3D decoder · TripoSplat VAE",
  "准备保留背景重建": "Preparing reconstruction with background", "准备从原图重建主体": "Preparing source reconstruction",
  "本地 TripoSplat · 完整图像 → 三维重建 → 对齐参考机位": "Local TripoSplat · full image → 3D reconstruction → camera alignment",
  "本地 TripoSplat · 去背景 → 三维重建 → 对齐参考机位": "Local TripoSplat · remove background → 3D reconstruction → camera alignment",
  "载入三维主体和参考机位": "Loading 3D subject and source camera", "原图三维重建已载入 · 拖动调整机位后应用": "3D source ready · adjust the view, then click Apply to node",
  "原图重建未完成 · 可重试": "Reconstruction incomplete · retry", "原图已改变，请重新重建": "Source changed. Reconstruct it again.", "请先连接或导入原图": "Connect or import a source image first",
  "快照已保存 · 正在应用到节点": "Camera saved · applying to node", "场景快照已保存": "Scene snapshot saved", "已载入上次应用的场景": "Loaded the previously applied camera",
  "连接或上传原图，重建对应的三维主体": "Read the source frame, reconstruct in 3D, then choose your camera",
  "连线原图已更新 · 应用后保存到场景": "Source updated · click Apply to node to save it to the scene",
  "无效的场景快照": "Invalid camera snapshot. Open Studio and apply the camera again.", "无法验证已保存的场景，请重新应用": "Could not verify the saved camera. Apply it again.",
  "参考图已变化，请重新读取并重建主体": "Source changed. Read it again and reconstruct the subject.", "上游已变化，请重新打开工作台读取原图": "Source nodes changed. Reopen Studio and read the source again.",
  "参考图连线未能解析，请检查上游是否被禁用": "Source connection could not be resolved. Check whether the source nodes are disabled.",
  "工作流已改变，请重新打开工作台": "Workflow changed. Reopen Studio.", "上游已变化，请重新读取图像": "Source changed. Read the image again.",
  "场景在保存时发生变化，请重新应用": "Scene changed while saving. Apply it again.", "保存失败": "Save failed", "工作台已关闭": "Studio closed",
  "上次应用的场景不在本机，已回到空白场景 · 重建主体或导入 GLB 后再应用": "Saved scene is missing on this computer. Reconstruct the source or import a GLB, then Apply to node.",
  "网格与控制器不会进入粗图。": "Grids and controls are excluded from the guide.", "请先载入三维主体。": "Reconstruct or load a 3D subject first.",
  "LoRA 强度输出 1 → AnyAngle": "LoRA strength 1 → AnyAngle", "LoRA 强度输出 0 → 使用底模": "LoRA strength 0 → base model",
  "AnyAngle 必须使用当前机位粗图。请把 LoRA 强度输出接至模型加载器。": "AnyAngle uses the current camera guide. Connect LoRA strength to the model loader.",
  "姿势 / 重建来源": "Pose / reconstruction source", "实际输出": "Actual output",
  "场景人物": "Scene people", "＋ 添加人物": "+ Add person", "复制": "Duplicate", "删除": "Delete", "名称": "Name", "角色色": "Person colour",
  "选择角色编辑；Ctrl 点击可多选。显示决定输出，锁定保护动作与站位。": "Select a person to edit; Ctrl-click to select several. Visibility controls the output; locking protects pose and position.",
  "朝向 °": "Heading °", "尺度": "Scale", "拖动平面": "Drag plane", "视图平面 · 上下 / 左右": "View plane · up/down and left/right", "地面 · 前后 / 左右": "Ground · forward/back and left/right",
  "选中人物落地": "Ground selected people", "适合选中人物": "Frame selected people", "身份参考": "Identity reference", "与姿势来源独立": "Independent of pose source", "来源": "Source",
  "文字描述 · 不用照片": "Text description · no photo", "上传人物照片…": "Upload person photo…", "上传 / 更换照片…": "Upload / replace photo…", "共享左侧原图": "Shared source image", "已上传人物照片": "Uploaded person photo",
  "此角色身份照片": "Person identity photo", "合影中的人物区域描述": "Describe this person in the group photo", "例如：左侧戴眼镜的人": "For example: the person with glasses on the left",
  "外观 / 服装": "Appearance / clothing", "人物外观、服装、风格": "Appearance, clothing and style", "分别绑定人物身份": "Assign separate identities", "Qwen 底模配合“多人编码”节点使用": "Use Qwen base model with the multi-person encoder",
  "粗图使用角色色": "Use person colours in guide", "辅助区分人物；POSE 仍保留标准关节颜色": "Distinguishes people; pose guides keep standard joint colours", "读取连线人物照片": "Read connected person photos", "读取连线姿势关键点 · SDPose": "Read connected pose keypoints · SDPose",
  "显示人物": "Show person", "隐藏人物": "Hide person", "锁": "Locked", "调": "Edit", "解锁人物": "Unlock person", "锁定人物": "Lock person", "图层向前": "Move layer forward", "图层向后": "Move layer backward",
  "三维粗渲染": "3D camera guide", "OpenPose 姿势": "OpenPose", "Depth Anything 深度": "Depth Anything",
  "互动编排与道具": "Interactions and props", "编排": "Arrangement", "合影 · 面向镜头": "Group photo · face camera", "对话 · 面向彼此": "Conversation · face each other", "握手 · 对齐双手": "Handshake · align hands",
  "应用到选中人物": "Apply to selected people", "锁定人物保持原状。握手为一次 IK 对齐，之后可自由编辑；不模拟碰撞。": "Locked people stay unchanged. Handshake aligns the hands once; edit freely afterwards. Collisions are not simulated.",
  "再次对齐双手": "Align hands again", "清除接触锚点": "Clear contact points", "＋ 导入 GLB 道具": "+ Import GLB prop", "朝向°": "Heading °", "隐藏": "Hide", "显示": "Show", "解锁": "Unlock", "锁定": "Lock",
  "请先载入三维主体": "Reconstruct or load a 3D subject first", "原图重建主体没有可编辑骨架；请使用拍摄机位": "The reconstructed subject has no editable skeleton. Use Camera mode.",
  "需使用三维粗图、人偶骨架或三维 Canny；原图提取的结构图保持原视角": "Requires a 3D guide, mannequin pose or 3D Canny. Guides extracted from the source keep the original viewpoint.",
  "按角度步进或收藏机位批量渲染 / 生成": "Render or generate an angle range or saved cameras",
  "原图 → image_1；当前引导图 → image_2。更改顺序后请对应调整编码器连线。": "Source → image_1; guide → image_2. If you change the order, update the encoder connections to match.",
  "原图 → image_2；当前引导图 → image_1。更改顺序后请对应调整编码器连线。": "Source → image_2; guide → image_1. If you change the order, update the encoder connections to match.",
  "当前引导图 → image_1；无需连接原图。用附加描述定义人物、场景与风格。": "Guide → image_1; no source connection needed. Use Additional description for the person, setting and style.",
  "提示词按原文输出，不自动改写图片编号；可留空并在工作流中自行拼接。": "The prompt passes through unchanged, including image numbers. Leave it blank to build the prompt in the workflow.",
  "单图模式关闭 AnyAngle LoRA；请连接强度输出或移除旧工作流的 LoRA。": "Guide-only mode disables the AnyAngle LoRA. Connect its strength output or remove the LoRA from the workflow.",
  "单引导图模式使用 Qwen 底模": "Guide-only mode uses the Qwen base model",
  "当前工作流的 AnyAngle LoRA 强度仍固定。请连接 Studio 的强度输出，或移除 LoRA 加载器。": "The AnyAngle LoRA strength is fixed in this workflow. Connect Studio's strength output or remove the LoRA loader.",
  "修改人物动作请选 Qwen 底模 + POSE 姿势；AnyAngle 用于改变机位。": "For pose edits use Qwen base model with Pose. AnyAngle changes the camera viewpoint.",
  "原图结构与构图 · 应用到节点后输出当前引导图": "Source structure and framing · Apply to node to use this guide",
  "当前三维机位的引导图 · 切换 3D 工作台调整机位": "Guide from the current camera · switch to 3D studio to adjust the view",
  "点选人物 · 拖动调整站位 · 右键环绕 · 中键平移": "Select a person · drag to move · right-drag to orbit · middle-drag to pan",
  "点选关节 / 拖 IK 手脚 · 右键环绕 · 中键平移": "Select joints / drag hand and foot controls · right-drag to orbit · middle-drag to pan",
  "点选关节 / 拖 IK 手脚 · 右键环绕 · 中键平移 · 拍摄机位保持不变": "Select joints / drag hand and foot controls · right-drag to orbit · middle-drag to pan · output camera stays fixed",
  "右键环绕 · 中键平移 · 可将当前视图设为机位": "Right-drag to orbit · middle-drag to pan · use this view as the output camera",
  "当前场景是手动人偶；重建原图后可生成对应主体的粗图。": "This scene uses a mannequin. Reconstruct the source to create a guide of the actual subject.",
  "人偶可调整资产尺度；姿势、手势和关节可在编辑场景中修改。": "Adjust mannequin scale here; change pose, hands and joints in Edit scene.",
  "GLB 默认 Y 轴朝上。旋转资产以校准正面；资产尺度与镜头缩放相互独立。": "GLB uses Y-up. Rotate the asset to align its front. Asset scale and camera zoom are independent.",
  "预览生成失败，请重试": "Preview failed. Try again.", "引导图 PNG 已导出": "Guide PNG exported",
  "4 个重建模型已就绪 · 保留背景时无需 BiRefNet · 下次重建使用当前选择": "4 reconstruction models ready · BiRefNet is not needed with background enabled · these choices apply to the next reconstruction",
  "5 个模型已就绪 · 下次重建使用当前选择": "5 models ready · these choices apply to the next reconstruction",
  "模型选择已保存 · 点击从原图重建 3D 使用新选择": "Model choices saved · click Reconstruct 3D to use them",
  "请重启 ComfyUI 以启用新版模型选择功能": "Restart ComfyUI to enable model selection",
  "参考图已连接": "Source image connected", "结构图已连接": "Guide image connected",
  "TripoSplat · 原图主体": "TripoSplat · source subject", "TripoSplat · 保留背景": "TripoSplat · with background",
  "三维粗渲染 · 实际输出": "3D camera guide · actual output", "OpenPose 姿势 · 实际输出": "OpenPose · actual output", "Depth Anything 深度 · 实际输出": "Depth Anything · actual output", "Canny 轮廓 · 实际输出": "Canny edges · actual output",
}));

const PROTECTED = "script,style,textarea,input,option:not([value]),[contenteditable]:not([contenteditable='false']),#prompt-preview,#shots .rename,#saved-poses,#composition-list option:not([value='']),#reconstruction-model-fields option,.actor-name,#prop-list .prop-card > strong";
const ASSET_STATUS = new Set(["正在载入场景", "等待原图重建", "MakeHuman · 手动人偶", "GLB 场景", "TripoSplat · 原图主体", "TripoSplat · 保留背景"]);
const ATTRIBUTES = ["title", "aria-label", "placeholder", "alt"];

export function translateText(text) {
  if (typeof text !== "string") return text;
  const trimmed = text.trim();
  let translated = TEXT.get(trimmed);
  // Anchored, numeric-only runtime labels. Never substitute fragments inside
  // filenames, descriptions or other artist text.
  if (translated === undefined && /^实际输出 · image_\d+ · \d+ × \d+$/.test(trimmed)) {
    translated = trimmed.replace(/^实际输出/, "Actual output");
  }
  if (translated === undefined && /^预览即将输出到 image_\d+ 的实际引导图。$/.test(trimmed)) {
    translated = `Actual guide preview for ${trimmed.match(/image_\d+/)[0]}.`;
  }
  if (translated === undefined && /^当前会输出到 image_\d+ 的引导图$/.test(trimmed)) {
    translated = `Guide output to ${trimmed.match(/image_\d+/)[0]}`;
  }
  // Preserve layout whitespace. No partial substitutions: filenames and artist
  // text embedded in a message must never accidentally become translated data.
  return translated === undefined ? text : text.replace(trimmed, translated);
}

export function localizeTree(root) {
  if (!root) return;
  if (root.nodeType === 3) {
    // This element also displays a user-supplied asset filename. Only its known
    // built-in defaults are UI; never treat arbitrary filenames as labels.
    if (root.parentElement?.closest("#asset-label") && !ASSET_STATUS.has(root.nodeValue.trim())) return;
    if (!root.parentElement?.closest(PROTECTED)) {
      const translated = translateText(root.nodeValue);
      if (translated !== root.nodeValue) root.nodeValue = translated;
    }
    return;
  }
  if (root.nodeType !== 1 && root.nodeType !== 9) return;
  if (root.nodeType === 1) {
    if (root.matches("script,style,#prompt-preview,[contenteditable]:not([contenteditable='false'])")) return;
    for (const name of ATTRIBUTES) {
      const value = root.getAttribute(name);
      if (value != null) {
        const translated = translateText(value);
        if (translated !== value) root.setAttribute(name, translated);
      }
    }
    if (root.matches(PROTECTED)) return;
  }
  for (const child of root.childNodes || []) localizeTree(child);
}

export function isAnyAngleFrame(frame, origin) {
  try {
    const url = new URL(frame.src, origin);
    return url.origin === origin && /^\/extensions\/[^/]*(?:anyangle|qwen-image-2\.1-multiangle-t8)[^/]*\/editor\/index\.html$/i.test(url.pathname);
  } catch { return false; }
}

export function localizeEditor(doc) {
  if (!doc?.body || doc.documentElement.dataset.zuraAnyAngleEnglish) return null;
  doc.documentElement.dataset.zuraAnyAngleEnglish = "1";
  doc.documentElement.lang = "en";
  localizeTree(doc.body);
  const help = doc.createElement("p");
  help.id = "zura-anyangle-steps";
  help.textContent = "Read connected image → Reconstruct 3D → Adjust camera → Apply to node. Then run the workflow.";
  help.setAttribute("role", "note");
  help.style.cssText = "margin:0 0 14px;padding:10px;background:#163f49;color:#edfaff;font:13px/1.5 system-ui;border:1px solid #43808b;border-radius:6px";
  // The upstream header/workspace have fixed heights. Put guidance in the
  // existing scrolling panel rather than changing layout or canvas dimensions.
  doc.querySelector(".reference-section")?.prepend(help);
  const apply = doc.getElementById("apply");
  if (apply) {
    apply.title = "Save this camera back to the workflow. Closing Studio without applying leaves the previous camera unchanged.";
    apply.style.outline = "2px solid #89e5d2";
    apply.style.outlineOffset = "2px";
  }
  const observer = new doc.defaultView.MutationObserver(records => {
    for (const record of records) {
      if (record.type === "childList") for (const added of record.addedNodes) localizeTree(added);
      else localizeTree(record.target);
    }
  });
  observer.observe(doc.body, { childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ATTRIBUTES });
  doc.defaultView.addEventListener("pagehide", () => observer.disconnect(), { once: true });
  return observer;
}

export function cameraApplied(node) {
  try {
    const token = JSON.parse(node.widgets?.find(w => w.name === "snapshot")?.value || "null");
    return token?.version === 1 && /^[a-f0-9]{64}$/.test(token.id);
  } catch { return false; }
}

export function updateLaunchButton(node) {
  for (const widget of node.widgets || []) {
    if (widget.type === "button" && /AnyAngle Studio/.test(widget.name || "")) {
      widget.label = cameraApplied(node) ? "Edit AnyAngle Studio · camera applied" : "Open AnyAngle Studio · apply a camera first";
      widget.options = { ...widget.options, serialize: false };
      widget.serialize = false;
      widget.tooltip = "Read connected image, Reconstruct 3D, choose a view, then click Apply to node.";
    }
  }
}

app.registerExtension({
  name: "Zura.AnyAngleEnglish",
  setup() {
    const frames = new WeakSet();
    const attach = frame => {
      if (frames.has(frame) || !isAnyAngleFrame(frame, location.origin)) return;
      frames.add(frame);
      frame.title = "AnyAngle Studio · 3D camera and pose editor";
      const load = () => { try { localizeEditor(frame.contentDocument); } catch { /* Never cross origins. */ } };
      frame.addEventListener("load", load);
      load();
    };
    const scan = root => {
      if (root.nodeType !== 1) return;
      if (root.matches("iframe")) attach(root);
      root.querySelectorAll("iframe").forEach(attach);
    };
    const observer = new MutationObserver(records => {
      for (const record of records) for (const node of record.addedNodes) scan(node);
    });
    observer.observe(document.body, { childList: true, subtree: true });
    scan(document.body);
  },
  nodeCreated(node) {
    if ((node.comfyClass || node.type) !== "AnyAngleStudioT8") return;
    updateLaunchButton(node);
    const draw = node.onDrawForeground;
    node.onDrawForeground = function () { updateLaunchButton(this); return draw?.apply(this, arguments); };
  },
  afterConfigureGraph() {
    for (const node of app.graph?._nodes || []) if ((node.comfyClass || node.type) === "AnyAngleStudioT8") updateLaunchButton(node);
  },
});
