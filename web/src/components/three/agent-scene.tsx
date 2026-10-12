"use client";

import { Canvas, useFrame } from "@react-three/fiber";
import { Environment, Float, Lightformer, MeshDistortMaterial, Sparkles } from "@react-three/drei";
import { useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";
import { AGENTS, type AgentId } from "./agents";

/** The real agent graph as a 3D scene: the supervisor in the middle, the three specialists orbiting it.
 *  When a chat message is answered, the specialist that handled it lights up and a packet travels along its link.
 *  Between real messages it idles by pinging each specialist in turn, so the scene never looks frozen. */

const IDLE_EVERY = 3.2; // seconds between ambient pings
const PACKET_TIME = 0.7; // seconds for a packet to reach a specialist

type Activity = { agent: AgentId; start: number; real: boolean };

function orbitPosition(a: (typeof AGENTS)[number], t: number, out: THREE.Vector3) {
  const angle = a.phase + t * a.speed;
  return out.set(Math.cos(angle) * a.radius, Math.sin(angle) * a.radius * Math.sin(a.tilt), Math.sin(angle) * a.radius * Math.cos(a.tilt));
}

type Extra = { pointer: React.RefObject<{ x: number; y: number }>; labels: React.RefObject<(HTMLElement | null)[]>; calm: boolean };

function Scene({ active, pulse, pointer, labels, onPick, calm }: SceneProps & Extra) {
  const group = useRef<THREE.Group>(null);
  const core = useRef<THREE.Mesh>(null);
  const shell = useRef<THREE.Mesh>(null);
  const orbs = useRef<(THREE.Mesh | null)[]>([]);
  const packets = useRef<(THREE.Mesh | null)[]>([]);
  const activity = useRef<Activity | null>(null);
  const seenPulse = useRef(pulse);
  const idleTurn = useRef(0);
  const tmp = useMemo(() => new THREE.Vector3(), []);
  const screen = useMemo(() => new THREE.Vector3(), []);

  // One line per specialist, re-pointed every frame from the core to its orb.
  const beams = useMemo(
    () =>
      AGENTS.map((a) => {
        const geometry = new THREE.BufferGeometry().setAttribute("position", new THREE.Float32BufferAttribute([0, 0, 0, 0, 0, 0], 3));
        const material = new THREE.LineBasicMaterial({ color: a.color, transparent: true, opacity: 0.15 });
        return new THREE.Line(geometry, material);
      }),
    [],
  );
  useEffect(() => () => beams.forEach((b) => { b.geometry.dispose(); (b.material as THREE.Material).dispose(); }), [beams]);

  // Labels are ordinary page elements placed over the canvas, re-positioned each frame from 3D to screen space.
  function place(el: HTMLElement | null | undefined, from: THREE.Object3D | null, x: number, y: number, z: number, camera: THREE.Camera, w: number, h: number) {
    if (!el || !from) return;
    from.localToWorld(screen.set(x, y, z)).project(camera);
    el.style.transform = `translate(-50%, -50%) translate(${((screen.x + 1) / 2) * w}px, ${((1 - screen.y) / 2) * h}px)`;
  }

  useFrame((state, delta) => {
    const t = state.clock.elapsedTime;
    const { camera, size } = state;
    // Keep the outer orbit in frame on narrow canvases.
    camera.position.z = Math.max(9.6, 8.8 / (size.width / size.height));
    const speed = calm ? 0.25 : 1;

    // A real answer takes over immediately; otherwise ping the next specialist every few seconds.
    if (pulse !== seenPulse.current) {
      seenPulse.current = pulse;
      if (active) activity.current = { agent: active, start: t, real: true };
    } else if (!activity.current || t - activity.current.start > (activity.current.real ? 6 : IDLE_EVERY)) {
      activity.current = { agent: AGENTS[idleTurn.current++ % AGENTS.length].id, start: t, real: false };
    }
    const act = activity.current;
    const since = act ? t - act.start : 99;

    if (group.current) {
      const p = pointer.current ?? { x: 0, y: 0 };
      group.current.rotation.y = THREE.MathUtils.damp(group.current.rotation.y, p.x * 0.5 + t * 0.04 * speed, 3, delta);
      group.current.rotation.x = THREE.MathUtils.damp(group.current.rotation.x, 0.18 - p.y * 0.3, 3, delta);
    }
    if (core.current) {
      // The supervisor flares as it routes, then settles.
      const flare = Math.exp(-since * 3);
      core.current.scale.setScalar(1 + flare * 0.12 + Math.sin(t * 1.6) * 0.015);
    }
    place(labels.current?.[AGENTS.length], core.current, 0, -1.6, 0, camera, size.width, size.height);
    if (shell.current) {
      shell.current.rotation.y += delta * 0.15 * speed;
      shell.current.rotation.z += delta * 0.08 * speed;
    }

    AGENTS.forEach((a, i) => {
      const pos = orbitPosition(a, t * speed, tmp);
      const orb = orbs.current[i];
      place(labels.current?.[i], orb, 0, 0.6, 0, camera, size.width, size.height);
      const lit = act?.agent === a.id ? Math.max(0, Math.min(1, (since - PACKET_TIME) * 4)) * Math.exp(-Math.max(0, since - PACKET_TIME) * (act.real ? 0.5 : 1.4)) : 0;
      if (orb) {
        orb.position.copy(pos);
        orb.scale.setScalar(1 + lit * 0.55);
        (orb.material as THREE.MeshStandardMaterial).emissiveIntensity = 0.6 + lit * 4;
      }
      const beam = beams[i];
      const attr = beam.geometry.getAttribute("position") as THREE.BufferAttribute;
      attr.setXYZ(1, pos.x, pos.y, pos.z);
      attr.needsUpdate = true;
      const travelling = act?.agent === a.id && since < PACKET_TIME;
      (beam.material as THREE.LineBasicMaterial).opacity = 0.12 + (travelling ? 0.7 : lit * 0.6);

      const packet = packets.current[i];
      if (packet) {
        packet.visible = travelling;
        if (travelling) packet.position.copy(pos).multiplyScalar(THREE.MathUtils.smootherstep(since / PACKET_TIME, 0, 1));
      }
    });
  });

  return (
    <group ref={group}>
      <Float speed={1.4} rotationIntensity={0.25} floatIntensity={0.6}>
        {/* The supervisor: a liquid, glossy core that reads every message first. */}
        <mesh ref={core}>
          <icosahedronGeometry args={[1, 24]} />
          <MeshDistortMaterial color="#0f766e" emissive="#064e3b" emissiveIntensity={0.6} roughness={0.12} metalness={0.75} distort={calm ? 0.15 : 0.32} speed={calm ? 0.6 : 1.8} />
        </mesh>
        <mesh ref={shell} scale={1.42}>
          <icosahedronGeometry args={[1, 1]} />
          <meshBasicMaterial color="#5eead4" wireframe transparent opacity={0.16} />
        </mesh>
      </Float>

      {AGENTS.map((a, i) => (
        <group key={a.id}>
          {/* The orbit path, tilted into the same plane the orb travels in. */}
          <mesh rotation={[Math.PI / 2 - a.tilt, 0, 0]}>
            <torusGeometry args={[a.radius, 0.004, 6, 160]} />
            <meshBasicMaterial color={a.color} transparent opacity={0.18} />
          </mesh>
          <primitive object={beams[i]} />
          <mesh ref={(m: THREE.Mesh | null) => { packets.current[i] = m; }} visible={false}>
            <sphereGeometry args={[0.07, 16, 16]} />
            <meshBasicMaterial color={a.color} toneMapped={false} />
          </mesh>
          <mesh ref={(m: THREE.Mesh | null) => { orbs.current[i] = m; }} onClick={() => onPick?.(a.id)}
            onPointerOver={() => { document.body.style.cursor = "pointer"; }} onPointerOut={() => { document.body.style.cursor = ""; }}>
            <sphereGeometry args={[0.26, 48, 48]} />
            <meshStandardMaterial color={a.color} emissive={a.color} emissiveIntensity={0.6} roughness={0.25} metalness={0.3} toneMapped={false} />
          </mesh>
        </group>
      ))}

      <Sparkles count={70} scale={[9, 6, 6]} size={2.2} speed={calm ? 0.05 : 0.3} opacity={0.6} color="#99f6e4" />
    </group>
  );
}

type SceneProps = {
  /** The specialist that answered the latest message, if any. */
  active: AgentId | null;
  /** Changes whenever a new answer arrives (the run id works well). */
  pulse: number;
  onPick?: (agent: AgentId) => void;
};

export default function AgentScene(props: SceneProps) {
  const wrap = useRef<HTMLDivElement>(null);
  const labels = useRef<(HTMLElement | null)[]>([]);
  const pointer = useRef({ x: 0, y: 0 });
  const [visible, setVisible] = useState(true);
  const [calm, setCalm] = useState(false);

  // Follow the cursor anywhere on the page, pause rendering when scrolled away, and slow down for reduced motion.
  useEffect(() => {
    const move = (e: PointerEvent) => {
      pointer.current = { x: (e.clientX / window.innerWidth) * 2 - 1, y: (e.clientY / window.innerHeight) * 2 - 1 };
    };
    window.addEventListener("pointermove", move, { passive: true });
    const io = new IntersectionObserver(([entry]) => setVisible(entry.isIntersecting));
    if (wrap.current) io.observe(wrap.current);
    const media = window.matchMedia("(prefers-reduced-motion: reduce)");
    const sync = () => setCalm(media.matches);
    sync();
    media.addEventListener("change", sync);
    return () => {
      window.removeEventListener("pointermove", move);
      io.disconnect();
      media.removeEventListener("change", sync);
    };
  }, []);

  return (
    <div ref={wrap} className="relative size-full">
      <Canvas camera={{ position: [0, 0.4, 9.6], fov: 42 }} dpr={[1, 1.75]} frameloop={visible ? "always" : "never"} gl={{ antialias: true, alpha: true }}>
        <ambientLight intensity={0.35} />
        <pointLight position={[4, 4, 4]} intensity={40} color="#a7f3d0" />
        <pointLight position={[-5, -2, -3]} intensity={25} color="#c4b5fd" />
        {/* Reflections from a few soft panels, built locally: no HDR file to download. */}
        <Environment resolution={128}>
          <Lightformer form="rect" intensity={2} position={[0, 4, -4]} scale={[8, 2, 1]} color="#ccfbf1" />
          <Lightformer form="circle" intensity={1.5} position={[-4, 0, 2]} scale={2} color="#ddd6fe" />
          <Lightformer form="ring" intensity={1} position={[4, -1, 3]} scale={2} color="#fef3c7" />
        </Environment>
        <Scene {...props} pointer={pointer} labels={labels} calm={calm} />
      </Canvas>
      {AGENTS.map((a, i) => (
        <button key={a.id} type="button" ref={(el) => { labels.current[i] = el; }} onClick={() => props.onPick?.(a.id)}
          className="absolute left-0 top-0 whitespace-nowrap rounded-full border border-white/15 bg-black/45 px-2.5 py-1 text-[11px] font-semibold text-white/90 backdrop-blur-md transition-colors hover:bg-white/15"
          style={{ transform: "translate(-200%, -200%)" }}>
          <span className="mr-1.5 inline-block size-1.5 rounded-full align-middle" style={{ background: a.color }} />
          {a.label} agent
        </button>
      ))}
      <span ref={(el) => { labels.current[AGENTS.length] = el; }} aria-hidden style={{ transform: "translate(-200%, -200%)" }}
        className="pointer-events-none absolute left-0 top-0 whitespace-nowrap rounded-full border border-white/15 bg-black/40 px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.18em] text-white/85 backdrop-blur-md">
        Supervisor
      </span>
    </div>
  );
}
