import * as THREE from 'https://unpkg.com/three@0.160.1/build/three.module.js';
import { OrbitControls } from 'https://unpkg.com/three@0.160.1/examples/jsm/controls/OrbitControls.js';
import { EffectComposer } from 'https://unpkg.com/three@0.160.1/examples/jsm/postprocessing/EffectComposer.js';
import { RenderPass } from 'https://unpkg.com/three@0.160.1/examples/jsm/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'https://unpkg.com/three@0.160.1/examples/jsm/postprocessing/UnrealBloomPass.js';

const sceneEl = document.getElementById('scene');
const details = document.getElementById('details');
const timeline = document.getElementById('timeline');
const threshold = document.getElementById('threshold');
const scrubber = document.getElementById('scrubber');
const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
renderer.setSize(window.innerWidth, window.innerHeight);
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
sceneEl.appendChild(renderer.domElement);

const scene = new THREE.Scene();
window.__THREE_SCENE__ = scene;
scene.fog = new THREE.FogExp2(0x020617, 0.018);
const camera = new THREE.PerspectiveCamera(62, window.innerWidth / window.innerHeight, 0.1, 2000);
window.__THREE_CAMERA__ = camera;
camera.position.set(0, 46, 86);
const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.autoRotate = true;
controls.autoRotateSpeed = 0.25;
const composer = new EffectComposer(renderer);
composer.addPass(new RenderPass(scene, camera));
const bloom = new UnrealBloomPass(new THREE.Vector2(window.innerWidth, window.innerHeight), 0.85, 0.42, 0.22);
composer.addPass(bloom);

scene.add(new THREE.AmbientLight(0x9bdcff, 0.55));
const key = new THREE.PointLight(0x67e8f9, 2, 260);
key.position.set(50, 70, 50);
scene.add(key);
const rim = new THREE.PointLight(0xa78bfa, 2, 240);
rim.position.set(-60, 40, -45);
scene.add(rim);

const raycaster = new THREE.Raycaster();
const pointer = new THREE.Vector2();
const nodeMeshes = [];
let sceneData = null;
let linkGroup = new THREE.Group();
let nodeGroup = new THREE.Group();
let particleGroup = new THREE.Group();
let dustGroup = new THREE.Group();
let pulseGroup = new THREE.Group();
scene.add(linkGroup, nodeGroup, particleGroup, dustGroup, pulseGroup);
const targetCamera = new THREE.Vector3(0, 46, 86);
const targetControls = new THREE.Vector3(0, 0, 0);
let replayEvents = [];
let draggedNode = null;

const floor = new THREE.GridHelper(160, 42, 0x00f5ff, 0x123451);
floor.position.y = -18;
floor.material.transparent = true;
floor.material.opacity = 0.22;
scene.add(floor);

function seedDust() {
  const geometry = new THREE.BufferGeometry();
  const positions = [];
  for (let i = 0; i < 420; i++) {
    positions.push((Math.random() - 0.5) * 180, (Math.random() - 0.2) * 90, (Math.random() - 0.5) * 180);
  }
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
  const material = new THREE.PointsMaterial({ color: 0x67e8f9, size: 0.26, transparent: true, opacity: 0.38, depthWrite: false });
  dustGroup.add(new THREE.Points(geometry, material));
}
seedDust();

function color(hex) { return new THREE.Color(hex || '#e5e7eb'); }
function api(path, options = {}) { return fetch(path, { headers: { 'Content-Type': 'application/json' }, ...options }).then(r => r.json()); }
function human(value) { return String(value ?? '--').replaceAll('_', ' '); }
function pct(value) { return `${Math.round(Number(value || 0) * 100)}%`; }

function positionFor(node, ringCounts) {
  const total = ringCounts[node.ring] || 1;
  const angle = (Math.PI * 2 * node.index) / total + node.ring * 0.41;
  const radius = 7 + node.ring * 9;
  const y = (node.ring - 2.5) * 4 + Math.sin(angle * 2) * 2;
  return new THREE.Vector3(Math.cos(angle) * radius, y, Math.sin(angle) * radius);
}

function clearGroup(group) {
  while (group.children.length) {
    const item = group.children.pop();
    item.geometry?.dispose?.();
    item.material?.dispose?.();
  }
}

function labelSprite(text) {
  const canvas = document.createElement('canvas');
  canvas.width = 256;
  canvas.height = 64;
  const ctx = canvas.getContext('2d');
  ctx.fillStyle = 'rgba(2,8,23,.72)';
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.strokeStyle = '#00f5ff';
  ctx.strokeRect(1, 1, canvas.width - 2, canvas.height - 2);
  ctx.font = '700 26px Inter, sans-serif';
  ctx.fillStyle = '#e2e8f0';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText(text, canvas.width / 2, canvas.height / 2);
  const texture = new THREE.CanvasTexture(canvas);
  const material = new THREE.SpriteMaterial({ map: texture, transparent: true, opacity: 0.86 });
  const sprite = new THREE.Sprite(material);
  sprite.scale.set(10, 2.5, 1);
  return sprite;
}

function addPulse(position, risk) {
  const ring = new THREE.Mesh(
    new THREE.RingGeometry(1.8, 2.1, 64),
    new THREE.MeshBasicMaterial({ color: risk > 0.7 ? 0xfb7185 : 0xffb800, transparent: true, opacity: 0.55, side: THREE.DoubleSide })
  );
  ring.position.copy(position);
  ring.rotation.x = Math.PI / 2;
  ring.userData = { age: 0, speed: 0.055 + risk * 0.05 };
  pulseGroup.add(ring);
}

function drawScene(data) {
  sceneData = data;
  nodeMeshes.length = 0;
  clearGroup(nodeGroup); clearGroup(linkGroup); clearGroup(particleGroup);
  const ringCounts = data.nodes.reduce((acc, node) => { acc[node.ring] = (acc[node.ring] || 0) + 1; return acc; }, {});
  const positions = new Map();
  for (const node of data.nodes) {
    const pos = positionFor(node, ringCounts);
    positions.set(node.id, pos);
    const risk = node.fault_probability || 0;
    const geometry = new THREE.IcosahedronGeometry(1.55 + risk * 2.2, 2);
    const material = new THREE.MeshStandardMaterial({ color: risk >= Number(threshold.value) ? 0xfb7185 : color(node.color), emissive: risk > 0 ? 0xff0044 : 0x00f5ff, emissiveIntensity: 0.6 + risk * 3.0, metalness: .6, roughness: .15 });
    const mesh = new THREE.Mesh(geometry, material);
    mesh.position.copy(pos);
    mesh.userData = node;
    mesh.name = node.id;
    nodeMeshes.push(mesh);
    nodeGroup.add(mesh);
    const label = labelSprite(node.id);
    label.position.copy(pos).add(new THREE.Vector3(0, 3.4 + risk * 2, 0));
    nodeGroup.add(label);
    const halo = new THREE.Mesh(new THREE.SphereGeometry(2.5 + risk * 3.5, 32, 20), new THREE.MeshBasicMaterial({ color: risk >= Number(threshold.value) ? 0xfb7185 : 0x67e8f9, transparent: true, opacity: 0.06 + risk * 0.16 }));
    halo.position.copy(pos);
    nodeGroup.add(halo);
    if (risk >= Number(threshold.value)) addPulse(pos, risk);
  }
  for (const link of data.links) {
    const a = positions.get(link.source); const b = positions.get(link.target);
    if (!a || !b) continue;
    const mid = a.clone().lerp(b, 0.5);
    mid.y += 5 + (link.risk || 0) * 12;
    const curve = new THREE.CatmullRomCurve3([a, mid, b]);
    const points = curve.getPoints(34);
    const geometry = new THREE.BufferGeometry().setFromPoints(points);
    const material = new THREE.LineBasicMaterial({ color: link.risk >= Number(threshold.value) ? 0xfb7185 : 0x38bdf8, transparent: true, opacity: 0.35 + link.risk * 0.55 });
    linkGroup.add(new THREE.Line(geometry, material));
    const particle = new THREE.Mesh(new THREE.SphereGeometry(0.28 + link.risk, 12, 8), new THREE.MeshBasicMaterial({ color: link.risk >= Number(threshold.value) ? 0xfb7185 : 0xffffff }));
    particle.userData = { curve, t: Math.random(), speed: 0.004 + Math.random() * 0.012 };
    particleGroup.add(particle);
  }
}

async function load() {
  const [scenePayload, replay] = await Promise.all([api('/api/visualization/scene'), api('/api/visualization/replay?limit=18')]);
  drawScene(scenePayload.data);
  replayEvents = replay.data.events || [];
  scrubber.max = Math.max(0, replayEvents.length - 1);
  scrubber.value = scrubber.max;
  timeline.innerHTML = replayEvents.map((e, idx) => `<div class="event" data-index="${idx}"><b>${e.event_type}</b><br>${e.timestamp}</div>`).join('');
}

function applyReplayEvent(index) {
  const event = replayEvents[index];
  if (!event || !sceneData?.nodes) return;
  const payload = event.payload || {};
  const nodeId = payload.node_id || payload.alert?.node_id || payload.top?.node_id;
  if (!nodeId) return;
  sceneData.nodes = sceneData.nodes.map(node => ({ ...node, fault_probability: node.id === nodeId ? Math.max(node.fault_probability || 0, payload.fault_probability || payload.probability || 0.75) : node.fault_probability || 0 }));
  sceneData.links = sceneData.links.map(link => ({ ...link, risk: link.source === nodeId || link.target === nodeId ? Math.max(link.risk || 0, 0.75) : link.risk || 0 }));
  drawScene(sceneData);
}

function animate() {
  requestAnimationFrame(animate);
  const time = performance.now() / 1000;
  camera.position.lerp(targetCamera, 0.035);
  controls.target.lerp(targetControls, 0.045);
  floor.material.opacity = 0.16 + Math.sin(time * 1.4) * 0.035;
  dustGroup.rotation.y += 0.0008;
  for (const mesh of nodeMeshes) {
    const risk = mesh.userData.fault_probability || 0;
    mesh.scale.setScalar(1 + Math.sin(time * 4 + mesh.position.x) * 0.04 + risk * 0.22);
  }
  for (const p of particleGroup.children) {
    p.userData.t = (p.userData.t + p.userData.speed) % 1;
    p.position.copy(p.userData.curve.getPoint(p.userData.t));
  }
  for (const ring of [...pulseGroup.children]) {
    ring.userData.age += ring.userData.speed;
    ring.scale.setScalar(1 + ring.userData.age * 8);
    ring.material.opacity = Math.max(0, 0.55 - ring.userData.age);
    if (ring.material.opacity <= 0.01) {
      ring.geometry.dispose();
      ring.material.dispose();
      pulseGroup.remove(ring);
    }
  }
  controls.update();
  composer.render();
}

window.addEventListener('resize', () => {
  camera.aspect = window.innerWidth / window.innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(window.innerWidth, window.innerHeight);
  composer.setSize(window.innerWidth, window.innerHeight);
});

window.addEventListener('pointerdown', (event) => {
  pointer.x = (event.clientX / window.innerWidth) * 2 - 1;
  pointer.y = -(event.clientY / window.innerHeight) * 2 + 1;
  raycaster.setFromCamera(pointer, camera);
  const hit = raycaster.intersectObjects(nodeMeshes)[0];
  if (hit) {
    if (event.shiftKey) {
      draggedNode = hit.object;
      controls.enabled = false;
      return;
    }
    const pos = hit.object.position.clone();
    targetControls.copy(pos);
    targetCamera.copy(pos.clone().add(new THREE.Vector3(12, 12, 18)));
    showNodeDetails(hit.object.userData);
  }
});

window.addEventListener('pointermove', (event) => {
  if (!draggedNode) return;
  pointer.x = (event.clientX / window.innerWidth) * 2 - 1;
  pointer.y = -(event.clientY / window.innerHeight) * 2 + 1;
  raycaster.setFromCamera(pointer, camera);
  const plane = new THREE.Plane(new THREE.Vector3(0, 1, 0), -draggedNode.position.y);
  const next = new THREE.Vector3();
  raycaster.ray.intersectPlane(plane, next);
  draggedNode.position.copy(next);
});

window.addEventListener('pointerup', () => {
  draggedNode = null;
  controls.enabled = true;
});

window.addEventListener('contextmenu', async (event) => {
  event.preventDefault();
  pointer.x = (event.clientX / window.innerWidth) * 2 - 1;
  pointer.y = -(event.clientY / window.innerHeight) * 2 + 1;
  raycaster.setFromCamera(pointer, camera);
  const hit = raycaster.intersectObjects(nodeMeshes)[0];
  if (!hit) return;
  await api('/api/fault/inject', { method: 'POST', body: JSON.stringify({ slice_id: hit.object.userData.slice_id || 'slice_1', node_id: hit.object.userData.id, fault_type: 'congestion', severity: 0.85 }) });
  await load();
});

document.getElementById('reload').addEventListener('click', load);
document.getElementById('demo').addEventListener('click', async () => { await api('/api/demo/run', { method: 'POST', body: JSON.stringify({ slice_id: 'slice_1', node_id: 'upf_1', fault_type: 'congestion', severity: 0.9, ticks: 12 }) }); await load(); });
threshold.addEventListener('input', () => sceneData && drawScene(sceneData));
scrubber.addEventListener('input', () => applyReplayEvent(Number(scrubber.value)));

async function showNodeDetails(node) {
  const [explain, proactive] = await Promise.all([
    api(`/api/explain/node/${encodeURIComponent(node.id)}`).catch(() => null),
    api('/api/proactive/latest').catch(() => null),
  ]);
  const forecast = explain?.data?.forecast || proactive?.data?.forecasts?.find(f => f.node_id === node.id);
  details.innerHTML = `
    <div class="detail-card">
      <h3>${node.id}</h3>
      <p>${human(node.type || node.node_type)} • ${forecast ? human(forecast.fault_type) : 'normal monitoring'}</p>
      <div class="mini-grid">
        <span><b>Now</b>${pct(forecast?.risk_now || node.fault_probability || 0)}</span>
        <span><b>T+10</b>${pct(forecast?.risk_t_plus_10 || 0)}</span>
        <span><b>Action</b>${human(forecast?.recommended_action || 'monitor')}</span>
      </div>
      <p>${explain?.data?.headline || 'Click nodes to inspect risk, blast radius, and preventive action.'}</p>
      <code>${explain?.data?.theory?.equation || 'R(v)=σ(local risk + neighbor risk + centrality)'}</code>
    </div>`;
}

load();
animate();

function connectTwinWebSocket() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  const ws = new WebSocket(`${proto}://${location.host}/ws/telemetry`);
  ws.onmessage = (event) => {
    const payload = JSON.parse(event.data);
    if (payload.type !== 'tick' || !sceneData?.nodes) return;
    const riskByNode = new Map();
    for (const frame of payload.frames || []) {
      riskByNode.set(frame.node_id, frame.fault_label ? 0.9 : 0);
    }
    if (payload.alert?.node_id) riskByNode.set(payload.alert.node_id, payload.alert.fault_probability || 0.7);
    sceneData.nodes = sceneData.nodes.map(node => ({ ...node, fault_probability: Math.max(node.fault_probability || 0, riskByNode.get(node.id) || 0) }));
    sceneData.links = sceneData.links.map(link => ({ ...link, risk: Math.max(riskByNode.get(link.source) || 0, riskByNode.get(link.target) || 0, link.risk || 0) }));
    drawScene(sceneData);
  };
  ws.onclose = () => setTimeout(connectTwinWebSocket, 3000);
}

connectTwinWebSocket();
