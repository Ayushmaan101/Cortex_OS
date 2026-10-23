'use client';
import React, { useEffect, useState, useMemo, useRef, useCallback } from 'react';
import ReactFlow, {
  Background, Controls, MiniMap,
  useNodesState, useEdgesState,
  addEdge,
  type Node, type Edge, type NodeProps, type Connection,
  Handle, Position, ReactFlowProvider, useReactFlow,
} from 'reactflow';
import 'reactflow/dist/style.css';

// ── Types ─────────────────────────────────────────────────────────────────────
interface Session { id: string; name: string; created_at: string; }
interface KnowledgeNode {
  id: string; 
  parent_id: string | null; 
  parent_ids?: string[]; // NEW: Support multiple parents
  content: string; 
  depth: number;
  created_at: string; 
  session_id: string; 
  similarity?: number; 
  x?: number;             // optional layout coordinates from backend
  y?: number;
  children?: KnowledgeNode[];
}
interface EdgeData {
  id: string;
  source_id: string;
  target_id: string;
  session_id: string;
}
interface InboxArticle {
  id: string; title: string; summary: string; link: string;
  date: string; source: string; source_id: string; emoji: string;
}
interface HarvestSource { id: string; label: string; emoji: string; }
interface ArrangeSuggestion {
  source_id: string; target_parent_id: string | null;
  reason: string; source_content: string; target_content: string;
}
interface SavedSynthesis {
  id: string; node_id: string; session_id: string;
  tone: string; content: string; title: string; saved_at: string;
}
type Tone = 'researcher' | 'student' | 'executive' | 'creative';
type AppMode = 'list' | 'flow' | 'search' | 'firehose';
type AddMode = 'quick' | 'deep';

const TONES: { id: Tone; label: string; icon: string; color: string }[] = [
  { id: 'researcher', label: 'Researcher', icon: '⚗',  color: '#a855f7' },
  { id: 'student',    label: 'Student',    icon: '📖', color: '#06b6d4' },
  { id: 'executive',  label: 'Executive',  icon: '⚡', color: '#f59e0b' },
  { id: 'creative',   label: 'Creative',   icon: '✦',  color: '#f472b6' },
];

const DEPTH_COLORS = [
  { border: '#a855f7', glow: 'rgba(168,85,247,.22)',  text: '#c084fc', dot: '#a855f7' },
  { border: '#06b6d4', glow: 'rgba(6,182,212,.22)',   text: '#22d3ee', dot: '#06b6d4' },
  { border: '#818cf8', glow: 'rgba(129,140,248,.22)', text: '#a5b4fc', dot: '#818cf8' },
  { border: '#f472b6', glow: 'rgba(244,114,182,.22)', text: '#f9a8d4', dot: '#f472b6' },
];

// ── Markdown renderer ─────────────────────────────────────────────────────────
function renderMarkdown(text: string, accent: string): React.ReactNode[] {
  const lines = text.split('\n'); const out: React.ReactNode[] = []; let k = 0;
  const inline = (s: string) => s.split(/(\*\*[^*]+\*\*)/g).map((p, i) =>
    p.startsWith('**') && p.endsWith('**')
      ? <strong key={i} style={{ color: '#e2e8f0', fontWeight: 700 }}>{p.slice(2, -2)}</strong> : p);
  for (let i = 0; i < lines.length; i++) {
    const l = lines[i];
    if (l.startsWith('## '))
      out.push(<div key={k++} style={{ color: accent, fontSize: '10px', fontWeight: 700, letterSpacing: '0.2em', textTransform: 'uppercase', marginTop: '20px', marginBottom: '8px', paddingBottom: '6px', borderBottom: `1px solid ${accent}30`, display: 'flex', alignItems: 'center', gap: '8px' }}><span style={{ opacity: .5 }}>◈</span>{l.slice(3)}</div>);
    else if (l.startsWith('- ') || l.startsWith('• '))
      out.push(<div key={k++} style={{ display: 'flex', gap: '10px', alignItems: 'flex-start', marginBottom: '6px', paddingLeft: '4px' }}><span style={{ color: accent, flexShrink: 0, marginTop: '1px', fontSize: '10px', opacity: .7 }}>▸</span><span style={{ color: '#8892a4', fontSize: '13px', lineHeight: '1.7' }}>{inline(l.slice(2))}</span></div>);
    else if (/^\d+\.\s/.test(l)) {
      const n = l.match(/^(\d+)\.\s/)![1];
      out.push(<div key={k++} style={{ display: 'flex', gap: '10px', alignItems: 'flex-start', marginBottom: '8px', paddingLeft: '4px' }}><span style={{ color: accent, flexShrink: 0, fontSize: '10px', fontWeight: 700, minWidth: '16px' }}>{n}.</span><span style={{ color: '#8892a4', fontSize: '13px', lineHeight: '1.7' }}>{inline(l.replace(/^\d+\.\s/, ''))}</span></div>);
    }
    else if (l.startsWith('**') && l.endsWith('**') && i < 3)
      out.push(<div key={k++} style={{ fontSize: '15px', fontWeight: 700, marginBottom: '16px', lineHeight: '1.4', background: `linear-gradient(135deg,${accent},#22d3ee)`, WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent' }}>{l.slice(2, -2)}</div>);
    else if (!l.trim()) out.push(<div key={k++} style={{ height: '8px' }} />);
    else if (l.trim()) out.push(<p key={k++} style={{ color: '#8892a4', fontSize: '13px', lineHeight: '1.8', margin: '0 0 8px', letterSpacing: '-0.01em' }}>{inline(l)}</p>);
  }
  return out;
}

// ── Expand Overlay ────────────────────────────────────────────────────────────
function ExpandOverlay({ node, sessionId, onClose, onDone }: {
  node: KnowledgeNode; sessionId: string; onClose: () => void; onDone: () => void;
}) {
  const [text, setText] = useState('');
  const [done, setDone] = useState(false);
  const [error, setError] = useState('');
  const abortRef = useRef<AbortController | null>(null);
  useEffect(() => {
    const ctrl = new AbortController(); abortRef.current = ctrl;
    (async () => {
      try {
        const res = await fetch('http://localhost:8000/nodes/expand', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ node_id: node.id, session_id: sessionId }), signal: ctrl.signal,
        });
        if (!res.ok) { setError(await res.text() || 'Expand failed'); return; }
        const reader = res.body!.getReader(); const dec = new TextDecoder();
        while (true) { const { done: d, value } = await reader.read(); if (d) break; setText(p => p + dec.decode(value, { stream: true })); }
        setDone(true); onDone();
      } catch (e: unknown) { if (e instanceof Error && e.name !== 'AbortError') setError('Network error'); }
    })();
    return () => ctrl.abort();
  }, [node.id, sessionId, onDone]);
  return (
    <div style={{ position: 'fixed', inset: 0, zIndex: 100, background: 'rgba(4,4,8,0.93)', backdropFilter: 'blur(24px)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '24px', animation: 'fadeIn .25s ease' }}
      onClick={e => { if (e.target === e.currentTarget) onClose(); }}>
      <div style={{ width: '100%', maxWidth: '700px', background: 'rgba(8,8,14,.99)', border: '1px solid rgba(168,85,247,.4)', borderRadius: '24px', boxShadow: '0 0 80px rgba(168,85,247,.15)', overflow: 'hidden', maxHeight: '80vh', display: 'flex', flexDirection: 'column' }}>
        <div style={{ padding: '18px 22px 14px', borderBottom: '1px solid rgba(168,85,247,.1)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <div style={{ width: '7px', height: '7px', borderRadius: '50%', background: done ? '#22d3ee' : '#a855f7', boxShadow: `0 0 8px ${done ? '#22d3ee' : '#a855f7'}`, animation: !done && !error ? 'pulse 1.2s ease infinite' : 'none' }} />
            <span style={{ color: done ? 'rgba(34,211,238,.7)' : 'rgba(168,85,247,.8)', fontSize: '9px', letterSpacing: '.25em', textTransform: 'uppercase' }}>{error ? '✕ Expand Failed' : done ? '🧠 Expansion Complete' : '🧠 Expanding...'}</span>
          </div>
          <button onClick={onClose} style={{ background: 'rgba(255,255,255,.04)', border: '1px solid rgba(255,255,255,.08)', borderRadius: '8px', color: 'rgba(148,163,184,.4)', padding: '6px 12px', fontSize: '10px', fontFamily: "'JetBrains Mono',monospace", letterSpacing: '.06em', cursor: 'pointer' }}>[ESC]</button>
        </div>
        <div style={{ padding: '20px 24px', overflowY: 'auto', flex: 1 }}>
          {error
            ? <p style={{ color: 'rgba(244,114,182,.7)', fontSize: '12px', fontFamily: "'JetBrains Mono',monospace" }}>{error}</p>
            : <div style={{ fontFamily: "'JetBrains Mono',monospace" }}>
              {!text && <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}><div style={{ width: '16px', height: '16px', borderRadius: '50%', border: '2px solid #a855f7', borderTopColor: 'transparent', animation: 'spin .8s linear infinite' }} /><span style={{ color: 'rgba(168,85,247,.5)', fontSize: '11px', letterSpacing: '.15em', textTransform: 'uppercase' }}>Running concept extraction...</span></div>}
              {renderMarkdown(text, '#a855f7')}
              {!done && text && <span style={{ display: 'inline-block', width: '2px', height: '14px', background: '#a855f7', marginLeft: '2px', verticalAlign: 'middle', animation: 'pulse .8s ease infinite' }} />}
            </div>}
          {done && <div style={{ marginTop: '16px', padding: '12px 16px', background: 'rgba(34,211,238,.05)', border: '1px solid rgba(34,211,238,.15)', borderRadius: '12px', color: 'rgba(34,211,238,.7)', fontSize: '11px', fontFamily: "'JetBrains Mono',monospace" }}>✓ Concept nodes added to workspace. Close this panel to see them.</div>}
        </div>
      </div>
    </div>
  );
}

// ── Synthesis Overlay (with Save button) ─────────────────────────────────────
function SynthesisOverlay({ node, sessionId, onClose, onSaved }: {
  node: KnowledgeNode; sessionId: string; onClose: () => void; onSaved?: (s: SavedSynthesis) => void;
}) {
  const [tone, setTone] = useState<Tone>('researcher');
  const [text, setText] = useState(''); const [done, setDone] = useState(false); const [error, setError] = useState(false); const [running, setRunning] = useState(false);
  const [saving, setSaving] = useState(false); const [savedId, setSavedId] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const at = TONES.find(t => t.id === tone)!;
  const run = useCallback(async (t: Tone) => {
    abortRef.current?.abort(); const ctrl = new AbortController(); abortRef.current = ctrl;
    setText(''); setDone(false); setError(false); setRunning(true); setSavedId(null);
    try {
      const res = await fetch('http://localhost:8000/synthesize', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ node_id: node.id, session_id: sessionId, tone: t }), signal: ctrl.signal });
      if (!res.ok) throw new Error();
      const reader = res.body!.getReader(); const dec = new TextDecoder();
      while (true) { const { done: d, value } = await reader.read(); if (d) break; setText(p => p + dec.decode(value, { stream: true })); }
      setDone(true);
    } catch (e: unknown) { if (e instanceof Error && e.name !== 'AbortError') setError(true); }
    finally { setRunning(false); }
  }, [node.id, sessionId]);

  const handleSave = async () => {
    if (!text || saving || savedId) return;
    setSaving(true);
    try {
      const titleMatch = text.match(/\*\*(.+?)\*\*/);
      const title = titleMatch ? titleMatch[1] : node.content.slice(0, 60);
      const r = await fetch('http://localhost:8000/synthesis/save', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ node_id: node.id, session_id: sessionId, tone, content: text, title }),
      });
      if (r.ok) { const saved = await r.json(); setSavedId(saved.id); onSaved?.(saved); }
    } catch { } finally { setSaving(false); }
  };

  useEffect(() => { run('researcher'); return () => abortRef.current?.abort(); }, []);
  return (
    <div style={{ position: 'fixed', inset: 0, zIndex: 100, background: 'rgba(4,4,8,0.93)', backdropFilter: 'blur(24px)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '24px', animation: 'fadeIn .25s ease' }}
      onClick={e => { if (e.target === e.currentTarget) onClose(); }}>
      <div style={{ width: '100%', maxWidth: '760px', background: 'rgba(8,8,14,.99)', border: `1px solid ${at.color}40`, borderRadius: '24px', boxShadow: `0 0 80px ${at.color}15`, overflow: 'hidden', maxHeight: '88vh', display: 'flex', flexDirection: 'column', transition: 'border-color .3s' }}>
        <div style={{ padding: '18px 22px 14px', borderBottom: `1px solid ${at.color}15`, background: `${at.color}05`, display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: '16px' }}>
          <div style={{ minWidth: 0 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '6px' }}>
              <div style={{ width: '7px', height: '7px', borderRadius: '50%', background: done ? '#22d3ee' : at.color, boxShadow: `0 0 8px ${done ? '#22d3ee' : at.color}`, animation: running ? 'pulse 1.2s ease infinite' : 'none', transition: 'all .5s' }} />
              <span style={{ color: done ? 'rgba(34,211,238,.7)' : `${at.color}b0`, fontSize: '9px', letterSpacing: '.25em', textTransform: 'uppercase' }}>{running ? `${at.icon} Synthesizing...` : done ? 'Synthesis Complete' : 'Ready'}</span>
              {savedId && <span style={{ color: 'rgba(34,211,238,.7)', fontSize: '9px', letterSpacing: '.15em', background: 'rgba(34,211,238,.1)', border: '1px solid rgba(34,211,238,.2)', borderRadius: '6px', padding: '2px 8px' }}>🔒 Saved</span>}
            </div>
            <p style={{ color: 'rgba(148,163,184,.4)', fontSize: '11px', fontFamily: "'JetBrains Mono',monospace", overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>◆ {node.content}</p>
          </div>
          <button onClick={onClose} style={{ background: 'rgba(255,255,255,.04)', border: '1px solid rgba(255,255,255,.08)', borderRadius: '8px', color: 'rgba(148,163,184,.4)', padding: '6px 12px', fontSize: '10px', fontFamily: "'JetBrains Mono',monospace", letterSpacing: '.06em', cursor: 'pointer', flexShrink: 0 }}>[ESC]</button>
        </div>
        <div style={{ padding: '12px 22px', borderBottom: '1px solid rgba(255,255,255,.04)', display: 'flex', gap: '8px', alignItems: 'center', flexWrap: 'wrap' }}>
          <span style={{ color: 'rgba(148,163,184,.25)', fontSize: '9px', letterSpacing: '.15em', textTransform: 'uppercase', flexShrink: 0, marginRight: '4px' }}>Tone</span>
          {TONES.map(t => <button key={t.id} onClick={() => { setTone(t.id); run(t.id); }} style={{ background: tone === t.id ? `${t.color}18` : 'transparent', border: `1px solid ${tone === t.id ? t.color + '60' : 'rgba(255,255,255,.07)'}`, borderRadius: '10px', padding: '6px 14px', color: tone === t.id ? t.color : 'rgba(148,163,184,.35)', fontSize: '10px', fontFamily: "'JetBrains Mono',monospace", letterSpacing: '.08em', cursor: 'pointer', transition: 'all .2s', display: 'flex', alignItems: 'center', gap: '6px' }}><span>{t.icon}</span><span>{t.label}</span></button>)}
        </div>
        <div style={{ padding: '22px 26px', overflowY: 'auto', flex: 1 }}>
          {error ? <p style={{ color: 'rgba(244,114,182,.6)', fontSize: '12px', fontFamily: "'JetBrains Mono',monospace" }}>Synthesis failed. Check GROQ_API_KEY.</p> : (
            <>
              <div style={{ background: `linear-gradient(135deg,${at.color}08,rgba(6,182,212,.03))`, border: `1px solid ${at.color}15`, borderRadius: '16px', padding: '22px 24px', position: 'relative', overflow: 'hidden', minHeight: '80px', transition: 'border-color .3s' }}>
                <div style={{ position: 'absolute', top: 0, left: 0, right: 0, height: '2px', background: `linear-gradient(90deg,${at.color},#06b6d4,transparent)` }} />
                {!text && running && <div style={{ display: 'flex', alignItems: 'center', gap: '10px', padding: '8px 0' }}><div style={{ width: '16px', height: '16px', borderRadius: '50%', border: `2px solid ${at.color}`, borderTopColor: 'transparent', animation: 'spin .8s linear infinite' }} /><span style={{ color: `${at.color}60`, fontSize: '11px', letterSpacing: '.15em', textTransform: 'uppercase' }}>Connecting to intelligence engine...</span></div>}
                <div style={{ fontFamily: "'JetBrains Mono',monospace" }}>{renderMarkdown(text, at.color)}</div>
                {running && text && <span style={{ display: 'inline-block', width: '2px', height: '14px', background: at.color, marginLeft: '2px', verticalAlign: 'middle', animation: 'pulse .8s ease infinite' }} />}
              </div>
              {done && (
                <div style={{ marginTop: '14px', display: 'flex', justifyContent: 'flex-end', gap: '8px', animation: 'fadeIn .3s ease' }}>
                  <button onClick={() => navigator.clipboard.writeText(text)} style={{ background: 'transparent', border: `1px solid ${at.color}30`, borderRadius: '8px', color: `${at.color}70`, padding: '6px 14px', fontSize: '9px', fontFamily: "'JetBrains Mono',monospace", letterSpacing: '.1em', textTransform: 'uppercase', cursor: 'pointer' }}>⧉ Copy</button>
                  <button onClick={handleSave} disabled={saving || !!savedId} style={{ background: savedId ? 'rgba(34,211,238,.1)' : saving ? 'rgba(255,255,255,.04)' : `${at.color}18`, border: `1px solid ${savedId ? 'rgba(34,211,238,.3)' : at.color + '40'}`, borderRadius: '8px', color: savedId ? '#22d3ee' : at.color, padding: '6px 14px', fontSize: '9px', fontFamily: "'JetBrains Mono',monospace", letterSpacing: '.1em', textTransform: 'uppercase', cursor: savedId || saving ? 'not-allowed' : 'pointer', transition: 'all .2s' }}>
                    {savedId ? '🔒 Saved' : saving ? '...' : '🔒 Save Insight'}
                  </button>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
// ── Saved Syntheses Panel ─────────────────────────────────────────────────────
function SavedSynthesesPanel({ sessionId, savedSyntheses, onDelete, onClose }: {
  sessionId: string; savedSyntheses: SavedSynthesis[];
  onDelete: (id: string) => void; onClose: () => void;
}) {
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const sessionSaved = savedSyntheses.filter(s => s.session_id === sessionId);
  if (sessionSaved.length === 0) return null;
  return (
    <div style={{ background: 'rgba(8,8,14,.98)', border: '1px solid rgba(34,211,238,.2)', borderRadius: '20px', padding: '20px', marginBottom: '20px', animation: 'fadeIn .3s ease' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '14px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span style={{ color: '#22d3ee', fontSize: '12px' }}>🔒</span>
          <span style={{ color: 'rgba(34,211,238,.7)', fontSize: '9px', letterSpacing: '.2em', textTransform: 'uppercase' }}>Saved Insights ({sessionSaved.length})</span>
        </div>
        <button onClick={onClose} style={{ background: 'none', border: 'none', color: 'rgba(148,163,184,.3)', fontSize: '9px', fontFamily: "'JetBrains Mono',monospace", letterSpacing: '.06em', textTransform: 'uppercase', cursor: 'pointer' }}>[hide]</button>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
        {sessionSaved.map(s => {
          const at = TONES.find(t => t.id === s.tone) ?? TONES[0];
          const isExpanded = expandedId === s.id;
          return (
            <div key={s.id} style={{ background: `${at.color}08`, border: `1px solid ${at.color}25`, borderRadius: '12px', overflow: 'hidden' }}>
              <div style={{ padding: '12px 14px', display: 'flex', alignItems: 'center', gap: '10px', cursor: 'pointer' }} onClick={() => setExpandedId(isExpanded ? null : s.id)}>
                <span style={{ color: at.color, fontSize: '12px', flexShrink: 0 }}>{at.icon}</span>
                <p style={{ color: '#c4cad4', fontSize: '12px', fontFamily: "'JetBrains Mono',monospace", flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', margin: 0 }}>{s.title}</p>
                <span style={{ color: 'rgba(148,163,184,.3)', fontSize: '9px', flexShrink: 0 }}>{new Date(s.saved_at).toLocaleDateString()}</span>
                <button onClick={e => { e.stopPropagation(); onDelete(s.id); }} style={{ background: 'none', border: 'none', color: 'rgba(244,114,182,.3)', fontSize: '11px', cursor: 'pointer', flexShrink: 0, padding: '2px 4px' }} onMouseEnter={e => (e.currentTarget.style.color = '#f472b6')} onMouseLeave={e => (e.currentTarget.style.color = 'rgba(244,114,182,.3)')}>✕</button>
                <span style={{ color: 'rgba(148,163,184,.2)', fontSize: '10px', transition: 'transform .2s', display: 'inline-block', transform: isExpanded ? 'rotate(180deg)' : 'none' }}>▾</span>
              </div>
              {isExpanded && (
                <div style={{ padding: '0 14px 14px', borderTop: `1px solid ${at.color}15` }}>
                  <div style={{ fontFamily: "'JetBrains Mono',monospace", paddingTop: '12px' }}>
                    {renderMarkdown(s.content, at.color)}
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: '10px' }}>
                    <button onClick={() => navigator.clipboard.writeText(s.content)} style={{ background: 'transparent', border: `1px solid ${at.color}30`, borderRadius: '8px', color: `${at.color}70`, padding: '5px 12px', fontSize: '9px', fontFamily: "'JetBrains Mono',monospace", letterSpacing: '.1em', textTransform: 'uppercase', cursor: 'pointer' }}>⧉ Copy</button>
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── AI Arrange Panel ──────────────────────────────────────────────────────────
function ArrangePanel({ sessionId, onApply, onClose }: {
  sessionId: string;
  onApply: (sourceId: string, targetParentId: string | null) => Promise<void>;
  onClose: () => void;
}) {
  const [mode, setMode] = useState<'coarse' | 'fine' | 'relations'>('coarse');
  const [loading, setLoading] = useState(false);
  const [suggestions, setSuggestions] = useState<ArrangeSuggestion[]>([]);
  const [applied, setApplied] = useState<Set<number>>(new Set());
  const [rejected, setRejected] = useState<Set<number>>(new Set());
  const [error, setError] = useState('');

  const fetchSuggestions = async (m: typeof mode) => {
    setLoading(true); setError(''); setSuggestions([]); setApplied(new Set()); setRejected(new Set());
    try {
      const r = await fetch('http://localhost:8000/nodes/arrange', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId, mode: m }),
      });
      if (!r.ok) throw new Error();
      const data = await r.json();
      setSuggestions(data.suggestions || []);
    } catch { setError('Failed to get suggestions'); }
    finally { setLoading(false); }
  };

  useEffect(() => { fetchSuggestions('coarse'); }, [sessionId]);

  const handleApply = async (idx: number, s: ArrangeSuggestion) => {
    await onApply(s.source_id, s.target_parent_id);
    setApplied(p => new Set([...p, idx]));
  };

  const modeColors = { coarse: '#a855f7', fine: '#06b6d4', relations: '#f59e0b' };
  const modeIcons = { coarse: '◎', fine: '⊞', relations: '⟡' };

  return (
    <div style={{ background: 'rgba(8,8,14,.98)', border: '1px solid rgba(168,85,247,.25)', borderRadius: '20px', padding: '20px', marginBottom: '20px', animation: 'fadeIn .3s ease' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '14px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span style={{ color: '#a855f7', fontSize: '9px', letterSpacing: '.2em', textTransform: 'uppercase' }}>⚙ AI Rearrangement Suggestions</span>
        </div>
        <button onClick={onClose} style={{ background: 'none', border: 'none', color: 'rgba(148,163,184,.3)', fontSize: '9px', fontFamily: "'JetBrains Mono',monospace", letterSpacing: '.06em', textTransform: 'uppercase', cursor: 'pointer' }}>[close]</button>
      </div>
      <div style={{ display: 'flex', gap: '6px', marginBottom: '14px' }}>
        {(['coarse', 'fine', 'relations'] as const).map(m => (
          <button key={m} onClick={() => { setMode(m); fetchSuggestions(m); }} style={{ flex: 1, background: mode === m ? `${modeColors[m]}15` : 'transparent', border: `1px solid ${mode === m ? modeColors[m] + '50' : 'rgba(255,255,255,.07)'}`, borderRadius: '10px', padding: '7px 10px', color: mode === m ? modeColors[m] : 'rgba(148,163,184,.3)', fontSize: '9px', fontFamily: "'JetBrains Mono',monospace", letterSpacing: '.08em', textTransform: 'uppercase', cursor: 'pointer', transition: 'all .2s' }}>
            {modeIcons[m]} {m}
          </button>
        ))}
      </div>
      {loading && <div style={{ display: 'flex', alignItems: 'center', gap: '10px', padding: '20px 0' }}><div style={{ width: '14px', height: '14px', borderRadius: '50%', border: '2px solid #a855f7', borderTopColor: 'transparent', animation: 'spin .8s linear infinite' }} /><span style={{ color: 'rgba(168,85,247,.5)', fontSize: '10px', letterSpacing: '.15em', textTransform: 'uppercase' }}>Analyzing workspace...</span></div>}
      {error && <p style={{ color: 'rgba(244,114,182,.6)', fontSize: '11px', fontFamily: "'JetBrains Mono',monospace" }}>{error}</p>}
      {!loading && suggestions.length === 0 && !error && <p style={{ color: 'rgba(148,163,184,.2)', fontSize: '10px', textAlign: 'center', padding: '20px 0', letterSpacing: '.15em', textTransform: 'uppercase' }}>No suggestions for current mode</p>}
      {suggestions.map((s, idx) => {
        const isApplied = applied.has(idx);
        const isRejected = rejected.has(idx);
        if (isRejected) return null;
        return (
          <div key={idx} style={{ background: isApplied ? 'rgba(34,211,238,.05)' : 'rgba(255,255,255,.02)', border: `1px solid ${isApplied ? 'rgba(34,211,238,.2)' : 'rgba(255,255,255,.06)'}`, borderRadius: '12px', padding: '12px 14px', marginBottom: '8px', transition: 'all .2s' }}>
            <div style={{ display: 'flex', alignItems: 'flex-start', gap: '10px' }}>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ display: 'flex', gap: '6px', alignItems: 'center', marginBottom: '6px', flexWrap: 'wrap' }}>
                  <span style={{ color: '#c084fc', fontSize: '10px', fontFamily: "'JetBrains Mono',monospace", overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: '180px' }}>{s.source_content}</span>
                  <span style={{ color: 'rgba(148,163,184,.3)', fontSize: '9px' }}>→</span>
                  <span style={{ color: '#22d3ee', fontSize: '10px', fontFamily: "'JetBrains Mono',monospace", overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: '180px' }}>{s.target_content}</span>
                </div>
                <p style={{ color: 'rgba(148,163,184,.4)', fontSize: '10px', margin: 0, lineHeight: '1.5', fontStyle: 'italic' }}>{s.reason}</p>
              </div>
              <div style={{ display: 'flex', gap: '6px', flexShrink: 0 }}>
                {isApplied
                  ? <span style={{ color: '#22d3ee', fontSize: '11px', padding: '4px 8px' }}>✓</span>
                  : <>
                    <button onClick={() => handleApply(idx, s)} style={{ background: 'rgba(34,211,238,.08)', border: '1px solid rgba(34,211,238,.2)', borderRadius: '7px', padding: '5px 10px', color: '#22d3ee', fontSize: '9px', fontFamily: "'JetBrains Mono',monospace", letterSpacing: '.08em', textTransform: 'uppercase', cursor: 'pointer', transition: 'all .15s' }} onMouseEnter={e => e.currentTarget.style.background = 'rgba(34,211,238,.18)'} onMouseLeave={e => e.currentTarget.style.background = 'rgba(34,211,238,.08)'}>Apply</button>
                    <button onClick={() => setRejected(p => new Set([...p, idx]))} style={{ background: 'transparent', border: '1px solid rgba(244,114,182,.15)', borderRadius: '7px', padding: '5px 8px', color: 'rgba(244,114,182,.4)', fontSize: '9px', cursor: 'pointer', transition: 'all .15s' }} onMouseEnter={e => e.currentTarget.style.color = '#f472b6'} onMouseLeave={e => e.currentTarget.style.color = 'rgba(244,114,182,.4)'}>✕</button>
                  </>
                }
              </div>
            </div>
          </div>
        );
      })}
      {suggestions.length > 0 && !loading && (
        <div style={{ display: 'flex', gap: '8px', marginTop: '10px' }}>
          <button onClick={() => suggestions.forEach((s, idx) => { if (!rejected.has(idx)) handleApply(idx, s); })} style={{ flex: 1, background: 'rgba(168,85,247,.08)', border: '1px solid rgba(168,85,247,.2)', borderRadius: '10px', padding: '8px', color: '#c084fc', fontSize: '9px', fontFamily: "'JetBrains Mono',monospace", letterSpacing: '.1em', textTransform: 'uppercase', cursor: 'pointer', transition: 'all .2s' }}>Apply All</button>
          <button onClick={() => fetchSuggestions(mode)} style={{ background: 'transparent', border: '1px solid rgba(255,255,255,.06)', borderRadius: '10px', padding: '8px 14px', color: 'rgba(148,163,184,.3)', fontSize: '9px', fontFamily: "'JetBrains Mono',monospace", letterSpacing: '.1em', textTransform: 'uppercase', cursor: 'pointer' }}>↺ Refresh</button>
        </div>
      )}
    </div>
  );
}

// ── Article Card ──────────────────────────────────────────────────────────────
function ArticleCard({ article, sessions, onAdd, onDismiss }: { article: InboxArticle; sessions: Session[]; onAdd: (id: string, sessionId: string, mode: AddMode) => void; onDismiss: (id: string) => void; }) {
  const [expanded, setExpanded] = useState(false);
  const [adding, setAdding] = useState(false);
  const [addMode, setAddMode] = useState<AddMode | null>(null);
  const [chosenSession, setChosenSession] = useState('');
  const [done, setDone] = useState(false);
  const handleAdd = async () => {
    if (!chosenSession || !addMode) return;
    setAdding(true); await onAdd(article.id, chosenSession, addMode); setAdding(false); setDone(true);
  };
  return (
    <div style={{ background: 'rgba(10,10,14,.9)', border: `1px solid ${done ? 'rgba(34,211,238,.2)' : 'rgba(255,255,255,.07)'}`, borderRadius: '16px', overflow: 'hidden', transition: 'all .2s', opacity: done ? .7 : 1 }}>
      <div style={{ padding: '16px 20px', display: 'flex', alignItems: 'flex-start', gap: '14px', cursor: 'pointer' }} onClick={() => setExpanded(p => !p)}>
        <span style={{ fontSize: '20px', flexShrink: 0, marginTop: '2px' }}>{article.emoji}</span>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '4px' }}>
            <span style={{ color: 'rgba(148,163,184,.35)', fontSize: '9px', letterSpacing: '.15em', textTransform: 'uppercase', fontFamily: "'JetBrains Mono',monospace" }}>{article.source}</span>
            {done && <span style={{ color: 'rgba(34,211,238,.6)', fontSize: '9px', letterSpacing: '.1em', textTransform: 'uppercase' }}>✓ Added</span>}
          </div>
          <p style={{ color: done ? 'rgba(148,163,184,.4)' : '#c4cad4', fontSize: '13px', fontFamily: "'JetBrains Mono',monospace", lineHeight: '1.5', margin: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: expanded ? 'normal' : 'nowrap' }}>{article.title}</p>
          {article.summary && <p style={{ color: 'rgba(148,163,184,.4)', fontSize: '11px', lineHeight: '1.6', margin: '6px 0 0', display: expanded ? 'block' : 'none' }}>{article.summary}</p>}
        </div>
        <div style={{ display: 'flex', gap: '8px', flexShrink: 0, alignItems: 'center' }}>
          <a href={article.link} target="_blank" rel="noopener noreferrer" onClick={e => e.stopPropagation()} style={{ color: 'rgba(148,163,184,.3)', fontSize: '11px', textDecoration: 'none', border: '1px solid rgba(255,255,255,.07)', borderRadius: '6px', padding: '4px 10px', fontFamily: "'JetBrains Mono',monospace", transition: 'all .15s' }} onMouseEnter={e => { (e.currentTarget as HTMLAnchorElement).style.color = '#c4cad4'; (e.currentTarget as HTMLAnchorElement).style.borderColor = 'rgba(255,255,255,.2)'; }} onMouseLeave={e => { (e.currentTarget as HTMLAnchorElement).style.color = 'rgba(148,163,184,.3)'; (e.currentTarget as HTMLAnchorElement).style.borderColor = 'rgba(255,255,255,.07)'; }}>↗</a>
          <span style={{ color: 'rgba(148,163,184,.2)', fontSize: '12px', transition: 'transform .2s', transform: expanded ? 'rotate(180deg)' : 'rotate(0deg)' }}>▾</span>
        </div>
      </div>
      {expanded && !done && (
        <div style={{ borderTop: '1px solid rgba(255,255,255,.05)', padding: '14px 20px 16px', background: 'rgba(168,85,247,.03)' }}>
          <div style={{ display: 'flex', gap: '8px', marginBottom: '12px' }}>
            <span style={{ color: 'rgba(148,163,184,.3)', fontSize: '9px', letterSpacing: '.15em', textTransform: 'uppercase', alignSelf: 'center', flexShrink: 0 }}>Add as</span>
            <button onClick={() => setAddMode('quick')} style={{ flex: 1, background: addMode === 'quick' ? 'rgba(6,182,212,.12)' : 'transparent', border: `1px solid ${addMode === 'quick' ? 'rgba(6,182,212,.4)' : 'rgba(255,255,255,.08)'}`, borderRadius: '10px', padding: '8px 12px', color: addMode === 'quick' ? '#22d3ee' : 'rgba(148,163,184,.4)', fontSize: '10px', fontFamily: "'JetBrains Mono',monospace", cursor: 'pointer', transition: 'all .15s', textAlign: 'left' }}>
              <div style={{ fontWeight: 700, letterSpacing: '.08em', textTransform: 'uppercase', marginBottom: '2px' }}>⚡ Quick Add</div>
              <div style={{ fontSize: '9px', opacity: .7 }}>Title + link + summary as 2 nodes</div>
            </button>
            <button onClick={() => setAddMode('deep')} style={{ flex: 1, background: addMode === 'deep' ? 'rgba(168,85,247,.12)' : 'transparent', border: `1px solid ${addMode === 'deep' ? 'rgba(168,85,247,.4)' : 'rgba(255,255,255,.08)'}`, borderRadius: '10px', padding: '8px 12px', color: addMode === 'deep' ? '#c084fc' : 'rgba(148,163,184,.4)', fontSize: '10px', fontFamily: "'JetBrains Mono',monospace", cursor: 'pointer', transition: 'all .15s', textAlign: 'left' }}>
              <div style={{ fontWeight: 700, letterSpacing: '.08em', textTransform: 'uppercase', marginBottom: '2px' }}>🧠 Deep Synthesis</div>
              <div style={{ fontSize: '9px', opacity: .7 }}>LLM extracts 4-6 key concepts</div>
            </button>
          </div>
          {addMode && (
            <div style={{ display: 'flex', gap: '8px', animation: 'fadeIn .2s ease' }}>
              <select value={chosenSession} onChange={e => setChosenSession(e.target.value)} style={{ flex: 1, background: 'rgba(255,255,255,.04)', border: '1px solid rgba(255,255,255,.1)', borderRadius: '10px', padding: '8px 14px', color: chosenSession ? '#e2e8f0' : 'rgba(148,163,184,.3)', fontSize: '11px', fontFamily: "'JetBrains Mono',monospace", cursor: 'pointer', outline: 'none' }}>
                <option value="" style={{ background: '#0d0d14' }}>Select workspace...</option>
                {sessions.map(s => <option key={s.id} value={s.id} style={{ background: '#0d0d14' }}>{s.name}</option>)}
              </select>
              <button onClick={handleAdd} disabled={!chosenSession || adding} style={{ padding: '8px 20px', borderRadius: '10px', border: 'none', background: chosenSession && !adding ? 'linear-gradient(135deg,#a855f7,#06b6d4)' : 'rgba(168,85,247,.12)', color: chosenSession && !adding ? '#fff' : 'rgba(168,85,247,.35)', fontSize: '10px', fontFamily: "'JetBrains Mono',monospace", fontWeight: 700, letterSpacing: '.1em', textTransform: 'uppercase', cursor: chosenSession && !adding ? 'pointer' : 'not-allowed', transition: 'all .2s', flexShrink: 0 }}>
                {adding ? <span style={{ display: 'flex', alignItems: 'center', gap: '6px' }}><span style={{ display: 'inline-block', width: '10px', height: '10px', borderRadius: '50%', border: '2px solid rgba(168,85,247,.4)', borderTopColor: '#a855f7', animation: 'spin .8s linear infinite' }} />Adding...</span> : 'Add →'}
              </button>
              <button onClick={() => onDismiss(article.id)} style={{ padding: '8px 12px', borderRadius: '10px', border: '1px solid rgba(244,114,182,.2)', background: 'transparent', color: 'rgba(244,114,182,.4)', fontSize: '10px', fontFamily: "'JetBrains Mono',monospace", cursor: 'pointer', flexShrink: 0, transition: 'all .15s' }} onMouseEnter={e => { e.currentTarget.style.color = '#f472b6'; e.currentTarget.style.borderColor = 'rgba(244,114,182,.4)'; }} onMouseLeave={e => { e.currentTarget.style.color = 'rgba(244,114,182,.4)'; e.currentTarget.style.borderColor = 'rgba(244,114,182,.2)'; }}>✕</button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Firehose Panel ────────────────────────────────────────────────────────────
function FirehosePanel({ sessions, onWorkspaceUpdated }: { sessions: Session[]; onWorkspaceUpdated: (sessionId: string) => void; }) {
  const [sources, setSources] = useState<HarvestSource[]>([]);
  const [inbox, setInbox] = useState<InboxArticle[]>([]);
  const [status, setStatus] = useState<{ running: boolean; last_run: string | null; next_run: string | null; inbox_count: number }>({ running: false, last_run: null, next_run: null, inbox_count: 0 });
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [filter, setFilter] = useState('all');
  const [search, setSearch] = useState('');
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const fetchStatus = useCallback(async () => { try { const r = await fetch('http://localhost:8000/harvest/status'); if (r.ok) setStatus(await r.json()); } catch { } }, []);
  const fetchInbox = useCallback(async () => { try { const r = await fetch('http://localhost:8000/harvest/inbox'); if (r.ok) setInbox(await r.json()); } catch { } }, []);
  useEffect(() => {
    (async () => { try { const r = await fetch('http://localhost:8000/harvest/sources'); if (r.ok) { const data = await r.json(); setSources(data); setSelected(new Set(data.map((s: { id: string }) => s.id))); } } catch { } })();
    fetchStatus(); fetchInbox();
  }, [fetchStatus, fetchInbox]);
  useEffect(() => {
    if (status.running) { pollRef.current = setInterval(() => { fetchStatus(); fetchInbox(); }, 2000); }
    else { if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; } }
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [status.running, fetchStatus, fetchInbox]);
  const triggerHarvest = async () => { try { await fetch('http://localhost:8000/harvest/run', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ source_ids: Array.from(selected) }) }); setStatus(s => ({ ...s, running: true })); } catch { } };
  const handleAdd = async (articleId: string, sessionId: string, mode: AddMode) => { try { await fetch('http://localhost:8000/harvest/inject', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ article_id: articleId, session_id: sessionId, depth: mode === 'deep' ? 'deep' : 'brief' }) }); onWorkspaceUpdated(sessionId); } catch { } };
  const handleDismiss = async (articleId: string) => { try { await fetch(`http://localhost:8000/harvest/inbox/${articleId}`, { method: 'DELETE' }); } catch { } setInbox(p => p.filter(a => a.id !== articleId)); };
  const filteredInbox = inbox.filter(a => { if (filter !== 'all' && a.source_id !== filter) return false; if (search && !a.title.toLowerCase().includes(search.toLowerCase())) return false; return true; });
  const sourceCounts = inbox.reduce((acc, a) => { acc[a.source_id] = (acc[a.source_id] || 0) + 1; return acc; }, {} as Record<string, number>);
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      <div style={{ background: 'linear-gradient(135deg,rgba(168,85,247,.08),rgba(6,182,212,.05))', border: '1px solid rgba(168,85,247,.2)', borderRadius: '20px', padding: '24px', position: 'relative', overflow: 'hidden' }}>
        <div style={{ position: 'absolute', top: 0, left: 0, right: 0, height: '2px', background: 'linear-gradient(90deg,#a855f7,#06b6d4,transparent)' }} />
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: '16px', flexWrap: 'wrap' }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '8px' }}>
              <div style={{ width: '8px', height: '8px', borderRadius: '50%', background: status.running ? '#22d3ee' : '#a855f7', boxShadow: `0 0 10px ${status.running ? '#22d3ee' : '#a855f7'}`, animation: status.running ? 'pulse 1s ease infinite' : 'none' }} />
              <span style={{ color: status.running ? 'rgba(34,211,238,.8)' : 'rgba(168,85,247,.7)', fontSize: '9px', letterSpacing: '.25em', textTransform: 'uppercase' }}>{status.running ? 'Harvesting Intelligence...' : 'Intelligence Firehose'}</span>
            </div>
            <p style={{ color: 'rgba(148,163,184,.5)', fontSize: '12px', lineHeight: '1.7', maxWidth: '460px', margin: '0 0 8px' }}>{inbox.length} articles in inbox across {Object.keys(sourceCounts).length} sources.</p>
            {status.last_run && <p style={{ color: 'rgba(148,163,184,.25)', fontSize: '10px', margin: 0, fontFamily: "'JetBrains Mono',monospace" }}>Last harvest: {new Date(status.last_run).toLocaleString()}{status.next_run && ` · Next: ${new Date(status.next_run).toLocaleTimeString()}`}</p>}
          </div>
          <button onClick={triggerHarvest} disabled={status.running} style={{ padding: '12px 24px', borderRadius: '14px', border: 'none', background: status.running ? 'rgba(168,85,247,.12)' : 'linear-gradient(135deg,#a855f7,#06b6d4)', color: status.running ? 'rgba(168,85,247,.4)' : '#fff', fontSize: '10px', fontFamily: "'JetBrains Mono',monospace", fontWeight: 700, letterSpacing: '.12em', textTransform: 'uppercase', cursor: status.running ? 'not-allowed' : 'pointer', boxShadow: status.running ? 'none' : '0 0 24px rgba(168,85,247,.4)', transition: 'all .2s' }}>
            {status.running ? <span style={{ display: 'flex', alignItems: 'center', gap: '8px' }}><span style={{ display: 'inline-block', width: '10px', height: '10px', borderRadius: '50%', border: '2px solid rgba(168,85,247,.4)', borderTopColor: '#a855f7', animation: 'spin .8s linear infinite' }} />Running...</span> : '⚡ Harvest Now'}
          </button>
        </div>
        <div style={{ display: 'flex', gap: '6px', marginTop: '16px', flexWrap: 'wrap', alignItems: 'center' }}>
          <span style={{ color: 'rgba(148,163,184,.25)', fontSize: '9px', letterSpacing: '.15em', textTransform: 'uppercase', marginRight: '4px' }}>Filter</span>
          <button onClick={() => setFilter('all')} style={{ background: filter === 'all' ? 'rgba(168,85,247,.15)' : 'transparent', border: `1px solid ${filter === 'all' ? 'rgba(168,85,247,.4)' : 'rgba(255,255,255,.07)'}`, borderRadius: '8px', padding: '4px 12px', color: filter === 'all' ? '#c084fc' : 'rgba(148,163,184,.35)', fontSize: '9px', fontFamily: "'JetBrains Mono',monospace", letterSpacing: '.08em', cursor: 'pointer', transition: 'all .15s' }}>All ({inbox.length})</button>
          {sources.filter(s => sourceCounts[s.id]).map(s => (<button key={s.id} onClick={() => setFilter(filter === s.id ? 'all' : s.id)} style={{ background: filter === s.id ? 'rgba(168,85,247,.15)' : 'transparent', border: `1px solid ${filter === s.id ? 'rgba(168,85,247,.4)' : 'rgba(255,255,255,.07)'}`, borderRadius: '8px', padding: '4px 12px', color: filter === s.id ? '#c084fc' : 'rgba(148,163,184,.35)', fontSize: '9px', fontFamily: "'JetBrains Mono',monospace", letterSpacing: '.06em', cursor: 'pointer', transition: 'all .15s' }}>{s.emoji} {s.label} ({sourceCounts[s.id] || 0})</button>))}
        </div>
      </div>
      <div style={{ position: 'relative' }}>
        <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search inbox..." style={{ width: '100%', background: 'rgba(255,255,255,.03)', border: '1px solid rgba(255,255,255,.07)', borderRadius: '12px', padding: '12px 42px 12px 16px', color: '#e2e8f0', fontSize: '12px', fontFamily: "'JetBrains Mono',monospace", outline: 'none', transition: 'border-color .2s' }} onFocus={e => (e.target.style.borderColor = 'rgba(168,85,247,.35)')} onBlur={e => (e.target.style.borderColor = 'rgba(255,255,255,.07)')} />
        <span style={{ position: 'absolute', right: '14px', top: '50%', transform: 'translateY(-50%)', color: 'rgba(148,163,184,.2)', fontSize: '12px' }}>⌕</span>
      </div>
      {status.running && inbox.length === 0 && <div style={{ background: 'rgba(8,8,14,.8)', border: '1px solid rgba(6,182,212,.15)', borderRadius: '16px', padding: '32px', textAlign: 'center' }}><div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '12px' }}><div style={{ width: '18px', height: '18px', borderRadius: '50%', border: '2px solid #06b6d4', borderTopColor: 'transparent', animation: 'spin .8s linear infinite' }} /><span style={{ color: 'rgba(6,182,212,.7)', fontSize: '10px', letterSpacing: '.2em', textTransform: 'uppercase' }}>Fetching intelligence across {selected.size} sources...</span></div></div>}
      {!status.running && filteredInbox.length === 0 && inbox.length === 0 && <div style={{ textAlign: 'center', padding: '60px 0' }}><p style={{ color: 'rgba(148,163,184,.15)', fontSize: '11px', letterSpacing: '.3em', textTransform: 'uppercase' }}>Inbox empty. Hit ⚡ Harvest Now to fetch latest articles.</p></div>}
      {filteredInbox.length > 0 && <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', animation: 'fadeIn .3s ease' }}><p style={{ color: 'rgba(148,163,184,.25)', fontSize: '9px', letterSpacing: '.2em', textTransform: 'uppercase' }}>{filteredInbox.length} articles{search ? ` matching "${search}"` : ''}</p>{filteredInbox.map(a => <ArticleCard key={a.id} article={a} sessions={sessions} onAdd={handleAdd} onDismiss={handleDismiss} />)}</div>}
    </div>
  );
}

// ── Sidebar ───────────────────────────────────────────────────────────────────
function Sidebar({ sessions, activeId, onSelect, onCreate, onRename, onDelete, collapsed, onToggle }: { sessions: Session[]; activeId: string | null; onSelect: (s: Session) => void; onCreate: (n: string) => void; onRename: (id: string, n: string) => void; onDelete: (id: string) => void; collapsed: boolean; onToggle: () => void; }) {
  const [newName, setNewName] = useState(''); const [creating, setCreating] = useState(false); const [renamingId, setRenamingId] = useState<string | null>(null); const [renameVal, setRenameVal] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);
  useEffect(() => { if (creating) setTimeout(() => inputRef.current?.focus(), 50); }, [creating]);
  return (
    <div style={{ width: collapsed ? '52px' : '240px', minHeight: '100vh', background: 'rgba(6,6,10,.97)', borderRight: '1px solid rgba(168,85,247,.1)', display: 'flex', flexDirection: 'column', transition: 'width .25s cubic-bezier(.16,1,.3,1)', position: 'fixed', left: 0, top: 0, bottom: 0, zIndex: 30, overflow: 'hidden' }}>
      <div style={{ padding: '20px 14px 12px', display: 'flex', alignItems: 'center', justifyContent: collapsed ? 'center' : 'space-between', borderBottom: '1px solid rgba(168,85,247,.08)' }}>
        {!collapsed && <span style={{ color: 'rgba(168,85,247,.5)', fontSize: '9px', letterSpacing: '.25em', textTransform: 'uppercase', fontFamily: "'JetBrains Mono',monospace" }}>Workspaces</span>}
        <button onClick={onToggle} style={{ background: 'none', border: 'none', color: 'rgba(148,163,184,.3)', fontSize: '14px', cursor: 'pointer', padding: '4px', borderRadius: '6px', transition: 'color .15s' }} onMouseEnter={e => (e.currentTarget.style.color = '#a855f7')} onMouseLeave={e => (e.currentTarget.style.color = 'rgba(148,163,184,.3)')}>{collapsed ? '◈' : '◧'}</button>
      </div>
      <div style={{ flex: 1, overflowY: 'auto', padding: collapsed ? '8px 6px' : '8px 10px' }}>
        {sessions.map(s => (
          <div key={s.id} style={{ marginBottom: '2px' }}>
            {renamingId === s.id && !collapsed ? (
              <form onSubmit={e => { e.preventDefault(); if (renameVal.trim()) { onRename(s.id, renameVal.trim()); setRenamingId(null); } }} style={{ padding: '4px 8px' }}>
                <input autoFocus value={renameVal} onChange={e => setRenameVal(e.target.value)} onBlur={() => setRenamingId(null)} onKeyDown={e => { if (e.key === 'Escape') setRenamingId(null); }} style={{ width: '100%', background: 'rgba(168,85,247,.1)', border: '1px solid rgba(168,85,247,.3)', borderRadius: '8px', padding: '6px 10px', color: '#e2e8f0', fontSize: '12px', fontFamily: "'JetBrains Mono',monospace", outline: 'none' }} />
              </form>
            ) : (
              <div onClick={() => onSelect(s)} title={collapsed ? s.name : undefined} style={{ display: 'flex', alignItems: 'center', justifyContent: collapsed ? 'center' : 'space-between', padding: collapsed ? '10px' : '8px 10px', borderRadius: '10px', cursor: 'pointer', background: activeId === s.id ? 'rgba(168,85,247,.12)' : 'transparent', border: `1px solid ${activeId === s.id ? 'rgba(168,85,247,.25)' : 'transparent'}`, transition: 'all .15s', gap: '8px' }} onMouseEnter={e => { if (activeId !== s.id) (e.currentTarget as HTMLDivElement).style.background = 'rgba(255,255,255,.04)'; }} onMouseLeave={e => { if (activeId !== s.id) (e.currentTarget as HTMLDivElement).style.background = 'transparent'; }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', minWidth: 0 }}>
                  <span style={{ color: activeId === s.id ? '#a855f7' : 'rgba(148,163,184,.35)', fontSize: '12px', flexShrink: 0 }}>◆</span>
                  {!collapsed && <span style={{ color: activeId === s.id ? '#e2e8f0' : 'rgba(148,163,184,.5)', fontSize: '12px', fontFamily: "'JetBrains Mono',monospace", overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{s.name}</span>}
                </div>
                {!collapsed && activeId === s.id && (
                  <div style={{ display: 'flex', gap: '4px', flexShrink: 0 }} onClick={e => e.stopPropagation()}>
                    <button onClick={() => { setRenamingId(s.id); setRenameVal(s.name); }} style={{ background: 'none', border: 'none', color: 'rgba(148,163,184,.3)', fontSize: '10px', cursor: 'pointer', padding: '2px 4px', borderRadius: '4px', transition: 'color .15s' }} onMouseEnter={e => (e.currentTarget.style.color = '#a855f7')} onMouseLeave={e => (e.currentTarget.style.color = 'rgba(148,163,184,.3)')}>✎</button>
                    <button onClick={() => { if (confirm(`Delete "${s.name}"?`)) onDelete(s.id); }} style={{ background: 'none', border: 'none', color: 'rgba(148,163,184,.3)', fontSize: '10px', cursor: 'pointer', padding: '2px 4px', borderRadius: '4px', transition: 'color .15s' }} onMouseEnter={e => (e.currentTarget.style.color = '#f472b6')} onMouseLeave={e => (e.currentTarget.style.color = 'rgba(148,163,184,.3)')}>✕</button>
                  </div>
                )}
              </div>
            )}
          </div>
        ))}
      </div>
      {!collapsed && (
        <div style={{ padding: '10px', borderTop: '1px solid rgba(168,85,247,.08)' }}>
          {creating ? (
            <form onSubmit={e => { e.preventDefault(); if (newName.trim()) { onCreate(newName.trim()); setNewName(''); setCreating(false); } }}>
              <input ref={inputRef} value={newName} onChange={e => setNewName(e.target.value)} placeholder="Session name..." onBlur={() => { if (!newName.trim()) setCreating(false); }} onKeyDown={e => { if (e.key === 'Escape') { setCreating(false); setNewName(''); } }} style={{ width: '100%', background: 'rgba(168,85,247,.08)', border: '1px solid rgba(168,85,247,.25)', borderRadius: '10px', padding: '8px 12px', color: '#e2e8f0', fontSize: '12px', fontFamily: "'JetBrains Mono',monospace", outline: 'none' }} />
            </form>
          ) : (
            <button onClick={() => setCreating(true)} style={{ width: '100%', background: 'rgba(168,85,247,.06)', border: '1px dashed rgba(168,85,247,.2)', borderRadius: '10px', padding: '8px', color: 'rgba(168,85,247,.4)', fontSize: '10px', fontFamily: "'JetBrains Mono',monospace", letterSpacing: '.1em', textTransform: 'uppercase', cursor: 'pointer', transition: 'all .2s' }} onMouseEnter={e => { e.currentTarget.style.background = 'rgba(168,85,247,.12)'; e.currentTarget.style.color = '#a855f7'; e.currentTarget.style.borderColor = 'rgba(168,85,247,.4)'; }} onMouseLeave={e => { e.currentTarget.style.background = 'rgba(168,85,247,.06)'; e.currentTarget.style.color = 'rgba(168,85,247,.4)'; e.currentTarget.style.borderColor = 'rgba(168,85,247,.2)'; }}>+ New Workspace</button>
          )}
        </div>
      )}
      {collapsed && <div style={{ padding: '10px 6px', borderTop: '1px solid rgba(168,85,247,.08)' }}><button onClick={onToggle} style={{ width: '100%', background: 'none', border: '1px dashed rgba(168,85,247,.2)', borderRadius: '8px', padding: '8px', color: 'rgba(168,85,247,.4)', fontSize: '12px', cursor: 'pointer' }}>+</button></div>}
    </div>
  );
}
// ── Node Card (WITH NODE-LEVEL SAVED SYNTHESES) ─────────────────────────────
interface NodeCardProps {
  node: KnowledgeNode;
  onBranch: (n: KnowledgeNode) => void;
  onSynthesize: (n: KnowledgeNode) => void;
  onExpand: (n: KnowledgeNode) => void;
  onDelete: (n: KnowledgeNode) => void;
  selectedId: string | null;
  isNew: boolean;
  isSearchResult?: boolean;
  savedSyntheses?: SavedSynthesis[]; // NEW: Show node-specific saved insights
  collapsedIds: Set<string>;
  toggleCollapse: (id: string) => void;
}

function NodeCard({ node, onBranch, onSynthesize, onExpand, onDelete, selectedId, isNew, isSearchResult = false, savedSyntheses = [], collapsedIds, toggleCollapse }: NodeCardProps) {
  const [showNodeSyntheses, setShowNodeSyntheses] = useState(false);
  const sel = node.id === selectedId;
  const hasKids = node.children && node.children.length > 0;
  const isCollapsed = collapsedIds.has(node.id);
  const C = DEPTH_COLORS[node.depth % 4];
  const simPct = node.similarity && !isNaN(node.similarity) ? Math.round(node.similarity * 100) : null;
  const totalChildren = node.children?.length ?? 0;
  const hasSourceChild = node.children?.some(c => c.content.trim().toLowerCase().startsWith('source:')) ?? false;
  const canExpand = !isSearchResult && hasSourceChild && totalChildren <= 3;
  
  // NEW: Filter saved syntheses for this specific node
  const nodeSyntheses = savedSyntheses.filter(s => s.node_id === node.id);
  
  return (
    <div style={{ animation: isNew ? 'nodeAppear .4s cubic-bezier(.16,1,.3,1) forwards' : undefined }}>
      <div style={{ border: `1px solid ${sel ? C.border : isSearchResult ? `${C.border}50` : 'rgba(255,255,255,.07)'}`, boxShadow: sel ? `0 0 28px ${C.glow},inset 0 0 20px ${C.glow}` : isSearchResult ? `0 0 16px ${C.glow}` : '0 2px 16px rgba(0,0,0,.5)', background: sel ? C.glow : 'rgba(10,10,14,.85)', backdropFilter: 'blur(12px)', transition: 'all .25s', borderRadius: '16px', padding: '18px 20px', position: 'relative', overflow: 'hidden' }}>
        {isSearchResult && simPct !== null && <div style={{ position: 'absolute', bottom: 0, left: 0, height: '2px', width: `${simPct}%`, background: `linear-gradient(90deg,${C.border},${C.dot}80)` }} />}
        {node.depth > 0 && !isSearchResult && <div style={{ position: 'absolute', left: '-5px', top: '22px', width: '10px', height: '10px', borderRadius: '50%', background: C.dot, boxShadow: `0 0 8px ${C.dot}` }} />}
        {isSearchResult && simPct !== null && <div style={{ position: 'absolute', top: '12px', right: '14px', background: C.glow, border: `1px solid ${C.border}50`, borderRadius: '6px', padding: '3px 8px', fontSize: '9px', color: C.text }}>{simPct}% MATCH</div>}
        <p style={{ color: sel ? '#f1f5f9' : '#8892a4', fontFamily: "'JetBrains Mono',monospace", fontSize: '13px', lineHeight: '1.7', margin: '0 0 14px', paddingRight: isSearchResult ? '90px' : '0' }}>{node.content}</p>
        
        {/* NEW: Show saved syntheses for this node */}
        {nodeSyntheses.length > 0 && (
          <div style={{ marginBottom: '12px', background: 'rgba(34,211,238,.08)', border: '1px solid rgba(34,211,238,.2)', borderRadius: '10px', padding: '10px 12px' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', cursor: 'pointer' }} onClick={() => setShowNodeSyntheses(!showNodeSyntheses)}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                <span style={{ fontSize: '11px' }}>🔒</span>
                <span style={{ color: '#22d3ee', fontSize: '10px', fontFamily: "'JetBrains Mono',monospace", letterSpacing: '.08em', textTransform: 'uppercase' }}>
                  {nodeSyntheses.length} Saved Insight{nodeSyntheses.length !== 1 ? 's' : ''}
                </span>
              </div>
              <span style={{ color: 'rgba(148,163,184,.3)', fontSize: '10px', transition: 'transform .2s', display: 'inline-block', transform: showNodeSyntheses ? 'rotate(180deg)' : 'none' }}>▾</span>
            </div>
            {showNodeSyntheses && (
              <div style={{ marginTop: '10px', paddingTop: '10px', borderTop: '1px solid rgba(34,211,238,.15)' }}>
                {nodeSyntheses.map(s => {
                  const at = TONES.find(t => t.id === s.tone) ?? TONES[0];
                  return (
                    <div key={s.id} style={{ marginBottom: '8px', padding: '8px', background: `${at.color}05`, border: `1px solid ${at.color}15`, borderRadius: '8px' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '4px' }}>
                        <span style={{ color: at.color, fontSize: '10px' }}>{at.icon}</span>
                        <span style={{ color: '#c4cad4', fontSize: '10px', fontFamily: "'JetBrains Mono',monospace", flex: 1 }}>{s.title}</span>
                        <button onClick={(e) => { e.stopPropagation(); navigator.clipboard.writeText(s.content); }} style={{ background: 'transparent', border: `1px solid ${at.color}20`, borderRadius: '4px', color: at.color, padding: '2px 6px', fontSize: '8px', cursor: 'pointer' }}>⧉</button>
                      </div>
                      <div style={{ fontSize: '9px', color: 'rgba(148,163,184,.4)', lineHeight: '1.4', maxHeight: '60px', overflow: 'hidden' }}>{s.content.slice(0, 150)}{s.content.length > 150 ? '...' : ''}</div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        )}
        
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
            <button onClick={() => onBranch(node)} style={{ color: C.text, border: `1px solid ${C.border}40`, background: 'transparent', borderRadius: '8px', padding: '4px 12px', fontSize: '10px', fontFamily: 'inherit', letterSpacing: '.08em', textTransform: 'uppercase', cursor: 'pointer', transition: 'all .2s' }} onMouseEnter={e => { e.currentTarget.style.borderColor = C.border; e.currentTarget.style.background = C.glow; }} onMouseLeave={e => { e.currentTarget.style.borderColor = `${C.border}40`; e.currentTarget.style.background = 'transparent'; }}>+ BRANCH</button>
            {hasKids && !isSearchResult && (
              <button onClick={() => toggleCollapse(node.id)} style={{ color: 'rgba(148,163,184,.6)', border: 'none', background: 'transparent', fontSize: '14px', cursor: 'pointer', padding: '0 6px', transition: 'color .2s' }}
                title={isCollapsed ? 'Show children' : 'Hide children'}
                onMouseEnter={e => (e.currentTarget.style.color = '#a855f7')}
                onMouseLeave={e => (e.currentTarget.style.color = 'rgba(148,163,184,.6)')}>
                {isCollapsed ? '▸' : '▾'}
              </button>
            )}
            {!isSearchResult && <button onClick={() => onSynthesize(node)} style={{ color: 'rgba(168,85,247,.6)', border: '1px solid rgba(168,85,247,.2)', background: 'transparent', borderRadius: '8px', padding: '4px 12px', fontSize: '10px', fontFamily: 'inherit', letterSpacing: '.08em', textTransform: 'uppercase', cursor: 'pointer', transition: 'all .2s' }} onMouseEnter={e => { e.currentTarget.style.color = '#c084fc'; e.currentTarget.style.borderColor = 'rgba(168,85,247,.5)'; e.currentTarget.style.background = 'rgba(168,85,247,.08)'; }} onMouseLeave={e => { e.currentTarget.style.color = 'rgba(168,85,247,.6)'; e.currentTarget.style.borderColor = 'rgba(168,85,247,.2)'; e.currentTarget.style.background = 'transparent'; }}>⚡ SYNTHESIZE</button>}
            {canExpand && <button onClick={() => onExpand(node)} style={{ color: 'rgba(34,211,238,.6)', border: '1px solid rgba(34,211,238,.2)', background: 'transparent', borderRadius: '8px', padding: '4px 12px', fontSize: '10px', fontFamily: 'inherit', letterSpacing: '.08em', textTransform: 'uppercase', cursor: 'pointer', transition: 'all .2s' }} onMouseEnter={e => { e.currentTarget.style.color = '#22d3ee'; e.currentTarget.style.borderColor = 'rgba(34,211,238,.5)'; e.currentTarget.style.background = 'rgba(34,211,238,.08)'; }} onMouseLeave={e => { e.currentTarget.style.color = 'rgba(34,211,238,.6)'; e.currentTarget.style.borderColor = 'rgba(34,211,238,.2)'; e.currentTarget.style.background = 'transparent'; }}>🧠 EXPAND</button>}
            {hasKids && !isSearchResult && <span style={{ color: C.text, background: C.glow, border: `1px solid ${C.border}30`, borderRadius: '6px', padding: '3px 8px', fontSize: '9px', textTransform: 'uppercase' }}>{node.children!.length} {node.children!.length === 1 ? 'branch' : 'branches'}</span>}
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <span style={{ color: 'rgba(148,163,184,.25)', fontSize: '9px' }}>{new Date(node.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
            {!isSearchResult && <button onClick={() => onDelete(node)} style={{ color: 'rgba(244,114,182,.3)', border: '1px solid rgba(244,114,182,.1)', background: 'transparent', borderRadius: '6px', padding: '3px 8px', fontSize: '10px', fontFamily: 'inherit', cursor: 'pointer', transition: 'all .2s', lineHeight: 1 }} onMouseEnter={e => { e.currentTarget.style.color = '#f472b6'; e.currentTarget.style.borderColor = 'rgba(244,114,182,.4)'; e.currentTarget.style.background = 'rgba(244,114,182,.08)'; }} onMouseLeave={e => { e.currentTarget.style.color = 'rgba(244,114,182,.3)'; e.currentTarget.style.borderColor = 'rgba(244,114,182,.1)'; e.currentTarget.style.background = 'transparent'; }} title="Delete node and all children">✕</button>}
          </div>
        </div>
      </div>
      {hasKids && !isSearchResult && !isCollapsed && (
        <div style={{ position: 'relative', marginTop: '12px', marginLeft: '28px' }}>
          <div style={{ position: 'absolute', left: 0, top: 0, bottom: 0, width: '1px', background: `linear-gradient(to bottom,${C.border}60,${C.border}10)` }} />
          <div style={{ paddingLeft: '28px', display: 'flex', flexDirection: 'column', gap: '12px' }}>
            {node.children!.map(c => <NodeCard key={c.id} node={c} onBranch={onBranch} onSynthesize={onSynthesize} onExpand={onExpand} onDelete={onDelete} selectedId={selectedId} isNew={false} savedSyntheses={savedSyntheses} collapsedIds={collapsedIds} toggleCollapse={toggleCollapse} />)}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Suggest Tray ──────────────────────────────────────────────────────────────
function SuggestTray({ suggestions, onAccept, onDismiss }: { suggestions: KnowledgeNode[]; onAccept: (n: KnowledgeNode) => void; onDismiss: () => void; }) {
  if (!suggestions.length) return null;
  const top = suggestions[0]; const simPct = top.similarity && !isNaN(top.similarity) ? Math.round(top.similarity * 100) : null; const others = suggestions.slice(1, 3);
  return (
    <div style={{ background: 'rgba(6,6,10,.97)', border: '1px solid rgba(168,85,247,.25)', borderRadius: '16px', padding: '14px 16px', marginBottom: '10px', backdropFilter: 'blur(20px)', boxShadow: '0 0 30px rgba(168,85,247,.12)', animation: 'traySlideUp .25s cubic-bezier(.16,1,.3,1)' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '10px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}><div style={{ width: '6px', height: '6px', borderRadius: '50%', background: '#a855f7', boxShadow: '0 0 6px #a855f7', animation: 'pulse 1.5s ease infinite' }} /><span style={{ color: 'rgba(168,85,247,.7)', fontSize: '9px', letterSpacing: '.2em', textTransform: 'uppercase' }}>Semantic Suggestion</span></div>
        <button onClick={onDismiss} style={{ color: 'rgba(148,163,184,.3)', background: 'none', border: 'none', fontSize: '9px', fontFamily: 'inherit', letterSpacing: '.06em', textTransform: 'uppercase', cursor: 'pointer' }}>[dismiss]</button>
      </div>
      <div onClick={() => onAccept(top)} style={{ background: 'rgba(168,85,247,.06)', border: '1px solid rgba(168,85,247,.2)', borderRadius: '12px', padding: '10px 14px', cursor: 'pointer', transition: 'all .2s', marginBottom: others.length ? '8px' : '0', position: 'relative', overflow: 'hidden' }} onMouseEnter={e => { (e.currentTarget as HTMLDivElement).style.background = 'rgba(168,85,247,.12)'; (e.currentTarget as HTMLDivElement).style.borderColor = 'rgba(168,85,247,.45)'; }} onMouseLeave={e => { (e.currentTarget as HTMLDivElement).style.background = 'rgba(168,85,247,.06)'; (e.currentTarget as HTMLDivElement).style.borderColor = 'rgba(168,85,247,.2)'; }}>
        {simPct !== null && <div style={{ position: 'absolute', bottom: 0, left: 0, height: '2px', width: `${simPct}%`, background: 'linear-gradient(90deg,#a855f7,#06b6d4)' }} />}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '4px' }}><span style={{ color: '#a855f7', fontSize: '9px', letterSpacing: '.1em', textTransform: 'uppercase' }}>Branch from this →</span>{simPct !== null && <span style={{ color: '#c084fc', fontSize: '9px', background: 'rgba(168,85,247,.15)', borderRadius: '4px', padding: '2px 6px' }}>{simPct}% similar</span>}</div>
        <p style={{ color: '#c4cad4', fontSize: '12px', lineHeight: '1.5', margin: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{top.content}</p>
      </div>
      {others.length > 0 && <div style={{ display: 'flex', gap: '8px' }}>{others.map(n => { const pct = n.similarity && !isNaN(n.similarity) ? Math.round(n.similarity * 100) : null; return <div key={n.id} onClick={() => onAccept(n)} style={{ flex: 1, background: 'rgba(6,182,212,.04)', border: '1px solid rgba(6,182,212,.15)', borderRadius: '10px', padding: '8px 12px', cursor: 'pointer', transition: 'all .2s', overflow: 'hidden' }} onMouseEnter={e => { (e.currentTarget as HTMLDivElement).style.background = 'rgba(6,182,212,.1)'; }} onMouseLeave={e => { (e.currentTarget as HTMLDivElement).style.background = 'rgba(6,182,212,.04)'; }}><div style={{ color: 'rgba(6,182,212,.5)', fontSize: '8px', letterSpacing: '.1em', marginBottom: '3px' }}>{pct !== null ? `${pct}%` : '—'} match</div><p style={{ color: '#8892a4', fontSize: '11px', lineHeight: '1.4', margin: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{n.content}</p></div>; })}</div>}
    </div>
  );
}

// ── Flow Node Popup (with Detach) ─────────────────────────────────────────────
function FlowNodePopup({ node, onBranch, onSynthesize, onExpand, onDelete, onDetach, onClose }: {
  node: KnowledgeNode; onBranch: (n: KnowledgeNode) => void; onSynthesize: (n: KnowledgeNode) => void;
  onExpand: (n: KnowledgeNode) => void; onDelete: (n: KnowledgeNode) => void;
  onDetach: (n: KnowledgeNode) => void; onClose: () => void;
}) {
  const C = DEPTH_COLORS[node.depth % 4];
  const totalChildren = node.children?.length ?? 0;
  const hasSourceChild = node.children?.some(c => c.content.trim().toLowerCase().startsWith('source:')) ?? false;
  const canExpand = hasSourceChild && totalChildren <= 3;
  const hasParent = !!node.parent_id || (node.parent_ids && node.parent_ids.length > 0); // NEW: Check parent_ids
  return (
    <div style={{ position: 'fixed', inset: 0, zIndex: 50, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '24px' }}
      onClick={e => { if (e.target === e.currentTarget) onClose(); }}>
      <div style={{ background: 'rgba(8,8,14,.98)', border: `1px solid ${C.border}60`, borderRadius: '20px', padding: '20px 24px', maxWidth: '480px', width: '100%', boxShadow: `0 0 60px ${C.glow}, 0 24px 80px rgba(0,0,0,.8)`, animation: 'fadeIn .2s ease' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '12px' }}>
          <div style={{ width: '6px', height: '6px', borderRadius: '50%', background: C.dot, boxShadow: `0 0 6px ${C.dot}` }} />
          <span style={{ color: `${C.text}80`, fontSize: '9px', letterSpacing: '.2em', textTransform: 'uppercase' }}>Depth {node.depth}</span>
          <span style={{ color: 'rgba(148,163,184,.2)', fontSize: '9px', marginLeft: 'auto' }}>{new Date(node.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
        </div>
        <p style={{ color: '#e2e8f0', fontFamily: "'JetBrains Mono',monospace", fontSize: '13px', lineHeight: '1.7', margin: '0 0 18px' }}>{node.content}</p>
        <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
          <button onClick={() => { onBranch(node); onClose(); }} style={{ flex: 1, minWidth: '80px', background: C.glow, border: `1px solid ${C.border}50`, borderRadius: '10px', padding: '8px 12px', color: C.text, fontSize: '10px', fontFamily: "'JetBrains Mono',monospace", letterSpacing: '.08em', textTransform: 'uppercase', cursor: 'pointer', transition: 'all .2s' }} onMouseEnter={e => { e.currentTarget.style.borderColor = C.border; }} onMouseLeave={e => { e.currentTarget.style.borderColor = `${C.border}50`; }}>+ Branch</button>
          <button onClick={() => { onSynthesize(node); onClose(); }} style={{ flex: 1, minWidth: '80px', background: 'rgba(168,85,247,.08)', border: '1px solid rgba(168,85,247,.25)', borderRadius: '10px', padding: '8px 12px', color: '#c084fc', fontSize: '10px', fontFamily: "'JetBrains Mono',monospace", letterSpacing: '.08em', textTransform: 'uppercase', cursor: 'pointer', transition: 'all .2s' }} onMouseEnter={e => { e.currentTarget.style.background = 'rgba(168,85,247,.18)'; }} onMouseLeave={e => { e.currentTarget.style.background = 'rgba(168,85,247,.08)'; }}>⚡ Synthesize</button>
          {canExpand && <button onClick={() => { onExpand(node); onClose(); }} style={{ flex: 1, minWidth: '80px', background: 'rgba(34,211,238,.06)', border: '1px solid rgba(34,211,238,.2)', borderRadius: '10px', padding: '8px 12px', color: '#22d3ee', fontSize: '10px', fontFamily: "'JetBrains Mono',monospace", letterSpacing: '.08em', textTransform: 'uppercase', cursor: 'pointer', transition: 'all .2s' }} onMouseEnter={e => { e.currentTarget.style.background = 'rgba(34,211,238,.14)'; }} onMouseLeave={e => { e.currentTarget.style.background = 'rgba(34,211,238,.06)'; }}>🧠 Expand</button>}
          {hasParent && (
            <button onClick={() => { onDetach(node); onClose(); }} style={{ flex: 1, minWidth: '80px', background: 'rgba(245,158,11,.06)', border: '1px solid rgba(245,158,11,.2)', borderRadius: '10px', padding: '8px 12px', color: '#f59e0b', fontSize: '10px', fontFamily: "'JetBrains Mono',monospace'", letterSpacing: '.08em', textTransform: 'uppercase', cursor: 'pointer', transition: 'all .2s' }} onMouseEnter={e => { e.currentTarget.style.background = 'rgba(245,158,11,.14)'; }} onMouseLeave={e => { e.currentTarget.style.background = 'rgba(245,158,11,.06)'; }} title="Detach from parent, make root">⟁ Detach</button>
          )}
          <button onClick={() => { onDelete(node); onClose(); }} style={{ background: 'rgba(244,114,182,.06)', border: '1px solid rgba(244,114,182,.2)', borderRadius: '10px', padding: '8px 12px', color: '#f472b6', fontSize: '10px', fontFamily: "'JetBrains Mono',monospace", cursor: 'pointer', transition: 'all .2s' }} onMouseEnter={e => { e.currentTarget.style.background = 'rgba(244,114,182,.14)'; }} onMouseLeave={e => { e.currentTarget.style.background = 'rgba(244,114,182,.06)'; }}>✕</button>
        </div>
      </div>
    </div>
  );
}

// ── Custom Flow Node ──────────────────────────────────────────────────────────
const FlowNode = React.memo(function FlowNode({ data }: NodeProps) {
  const { node, isSelected, isSuggested, onClick } = data as {
    node: KnowledgeNode; isSelected: boolean; isSuggested: boolean;
    onClick: (n: KnowledgeNode) => void;
  };
  const C = DEPTH_COLORS[node.depth % 4];
  const hasKids = (node.children?.length ?? 0) > 0;
  const words = node.content.split(' ');
  const preview = words.length > 9 ? words.slice(0, 9).join(' ') + '…' : node.content;
  const borderColor = isSuggested ? '#22d3ee' : isSelected ? C.border : `${C.border}55`;
  const bgColor = isSuggested ? 'rgba(34,211,238,.07)' : isSelected ? C.glow : 'rgba(10,10,16,.95)';
  const shadowStr = isSuggested
    ? '0 0 0 2px rgba(34,211,238,.4), 0 0 32px rgba(34,211,238,.25)'
    : isSelected ? `0 0 24px ${C.glow}, 0 0 48px ${C.glow}` : `0 0 12px ${C.glow}30, 0 4px 20px rgba(0,0,0,.6)`;
  return (
    <>
      <Handle type="target" position={Position.Top} style={{ background: C.dot, border: 'none', width: '7px', height: '7px', opacity: .8 }} />
      <div onClick={() => onClick(node)}
        style={{ background: bgColor, border: `1.5px solid ${borderColor}`, borderRadius: '14px', padding: '12px 16px', minWidth: '160px', maxWidth: '220px', cursor: 'pointer', boxShadow: shadowStr, transition: 'all .25s', position: 'relative', backdropFilter: 'blur(12px)', animation: isSuggested ? 'suggestPulse 2s ease infinite' : 'none' }}>
        <div style={{ position: 'absolute', top: 0, left: '16px', right: '16px', height: '2px', background: `linear-gradient(90deg,${C.border},${C.dot}80,transparent)`, borderRadius: '0 0 2px 2px' }} />
        {isSuggested && <div style={{ position: 'absolute', top: '-20px', left: '50%', transform: 'translateX(-50%)', background: 'rgba(34,211,238,.15)', border: '1px solid rgba(34,211,238,.3)', borderRadius: '6px', padding: '2px 8px', fontSize: '8px', color: '#22d3ee', letterSpacing: '.15em', textTransform: 'uppercase', whiteSpace: 'nowrap', fontFamily: "'JetBrains Mono',monospace" }}>◈ semantic match</div>}
        <p style={{ color: isSelected ? '#f1f5f9' : '#c4cad4', fontFamily: "'JetBrains Mono',monospace", fontSize: '11px', lineHeight: '1.55', margin: 0, wordBreak: 'break-word' }}>{preview}</p>
        {hasKids && <div style={{ marginTop: '8px', display: 'flex', alignItems: 'center', gap: '4px' }}><div style={{ width: '4px', height: '4px', borderRadius: '50%', background: C.dot, opacity: .6 }} /><span style={{ color: `${C.text}55`, fontSize: '8px', letterSpacing: '.1em' }}>{node.children!.length} branch{node.children!.length !== 1 ? 'es' : ''}</span></div>}
      </div>
      <Handle type="source" position={Position.Bottom} style={{ background: C.dot, border: 'none', width: '7px', height: '7px', opacity: .8 }} />
    </>
  );
});

const nodeTypes = { cortex: FlowNode };

// ── Layout: FIXED seed positions (only for NEW nodes) ────────────────────────
// seedPositions now accepts an optional occupied map so new nodes can avoid
// spots already taken by manually-placed nodes.  It also includes a simple
// buffer algorithm: if a candidate location is within `RADIUS` of any existing
// point, the function nudges the position until a clear zone is found.
function seedPositions(
  rawNodes: KnowledgeNode[],
  occupied: Record<string, { x: number; y: number }> = {}
): Record<string, { x: number; y: number }> {
  const LEVEL_H = 190;
  const SPLAY_W = 280;
  const positioned: Record<string, { x: number; y: number }> = {};

  const RADIUS = 200;        // "safe zone" radius
  const NUDGE = 250;         // amount to move when there is a conflict

  function findClear(x: number, y: number) {
    let nx = x;
    let ny = y;
    let attempts = 0;

    const conflictWith = (px: number, py: number) => {
      const dx = px - nx;
      const dy = py - ny;
      return Math.sqrt(dx * dx + dy * dy) < RADIUS;
    };

    while (true) {
      let conflict = false;
      for (const pos of Object.values(occupied)) {
        if (conflictWith(pos.x, pos.y)) { conflict = true; break; }
      }
      for (const pos of Object.values(positioned)) {
        if (conflictWith(pos.x, pos.y)) { conflict = true; break; }
      }
      if (!conflict || attempts++ > 10) break;
      // alternate nudges in x and y to spread out
      if (attempts % 2 === 0) nx += NUDGE;
      else ny += NUDGE;
    }
    return { x: nx, y: ny };
  }

  const roots = rawNodes.filter(
    n => !n.parent_id && (!n.parent_ids || n.parent_ids.length === 0)
  );
  const queue: { id: string; x: number; y: number }[] = [];

  // smart grid layout with jitter for roots to avoid stacking on fresh load
  const GRID_SPACING = 450;
  const JITTER = 40;
  roots.forEach((r, i) => {
    const x = i * GRID_SPACING;
    const y = (Math.random() - 0.5) * JITTER;
    const { x: cx, y: cy } = findClear(x, y);
    queue.push({ id: r.id, x: cx, y: cy });
  });

  while (queue.length) {
    const { id, x, y } = queue.shift()!;
    positioned[id] = { x, y };
    const children = rawNodes.filter(n => {
      if (n.parent_id === id) return true;
      if (n.parent_ids && n.parent_ids.includes(id)) return true;
      return false;
    });
    children.forEach((c, i) => {
      const rawX = x + (i - (children.length - 1) / 2) * SPLAY_W;
      const rawY = y + LEVEL_H;
      const { x: cx, y: cy } = findClear(rawX, rawY);
      queue.push({ id: c.id, x: cx, y: cy });
    });
  }

  rawNodes.forEach(n => {
    if (!positioned[n.id]) {
      const rnd = { x: Math.random() * 800 - 400, y: Math.random() * 600 - 100 };
      positioned[n.id] = findClear(rnd.x, rnd.y);
    }
  });
  return positioned;
}
// ── Graph Flow Inner (FIXED SMOOTH LAYOUT) ──────────────────────────────────
interface GraphFlowInnerProps {
  rawNodes: KnowledgeNode[];
  edges: EdgeData[];
  treeData: KnowledgeNode[];
  sessionId: string;
  selectedParentId: string | null;
  suggestedNodeIds: string[];
  onClickNode: (n: KnowledgeNode) => void;
  onEdgeConnect: (parentId: string, childId: string) => void;
  onEdgeDetach: (node: KnowledgeNode) => void;
  onNewNode: (content: string, parentId: string | null) => Promise<void>;
  onSetSelectedParent: (n: KnowledgeNode | null) => void;
  synthesisNode: KnowledgeNode | null;
  setSynthesisNode: (n: KnowledgeNode | null) => void;
  setExpandNode: (n: KnowledgeNode | null) => void;
  handleDeleteNode: (n: KnowledgeNode) => void;
  sidebarWidth: number;
  activeSessionName: string;
  mode: AppMode;
  setMode: (m: AppMode) => void;
  suggestions: KnowledgeNode[];
  suggestDismissed: boolean;
  setSuggestDismissed: (v: boolean) => void;
  flowContent: string;
  setFlowContent: (v: string) => void;
  flowSelectedParent: KnowledgeNode | null;
  setFlowSelectedParent: (n: KnowledgeNode | null) => void;
  submitting: boolean;
  handleFlowSubmit: (e: React.FormEvent) => void;
  handleFlowContentChange: (v: string) => void;
  onRequestArrange: () => void;
  showArrangePanel: boolean;
  collapsedIds: Set<string>;
}

function GraphFlowInner({
  rawNodes, edges, treeData, sessionId, selectedParentId, suggestedNodeIds,
  onClickNode, onEdgeConnect, onSetSelectedParent,
  sidebarWidth, activeSessionName, mode, setMode,
  suggestions, suggestDismissed, setSuggestDismissed,
  flowContent, flowSelectedParent, setFlowSelectedParent,
  submitting, handleFlowSubmit, handleFlowContentChange,
  onRequestArrange, showArrangePanel,
  collapsedIds,
}: GraphFlowInnerProps) {
  const { fitView } = useReactFlow();
  const posMemory = useRef<Record<string, { x: number; y: number }>>({});
  const lastSessionId = useRef<string>('');
  const lastNodeCount = useRef<number>(0);
  const initializedRef = useRef(false);

  // Initialize positions when session changes.  Pull any saved coords from
  // the backend; only auto‐seed nodes that still lack a spot.
  if (lastSessionId.current !== sessionId) {
    lastSessionId.current = sessionId;

    posMemory.current = {};
    rawNodes.forEach(n => {
      // ignore default zeros which indicate "no position set yet"
      if (
        typeof n.x === 'number' && typeof n.y === 'number' &&
        (n.x !== 0 || n.y !== 0)
      ) {
        posMemory.current[n.id] = { x: n.x, y: n.y };
      }
    });

    const needing = rawNodes.filter(n => !posMemory.current[n.id]);
    if (needing.length > 0) {
      const extra = seedPositions(needing, posMemory.current);
      Object.assign(posMemory.current, extra);
    }

    initializedRef.current = true;
  }

  // FIX: Only seed positions for NEW nodes, preserve existing positions
  useEffect(() => {
    const prev = lastNodeCount.current;
    const curr = rawNodes.length;
    
    if (curr > prev && prev > 0) {
      // Only consider genuinely new nodes that lack a stored coordinate
      const newNodes = rawNodes.filter(n => !posMemory.current[n.id]);
      
      if (newNodes.length > 0) {
        // when seeding we pass the existing memory so the buffer check can
        // avoid overlaps with manually-placed nodes.
        const tempPositioned = seedPositions(newNodes, posMemory.current);
        
        newNodes.forEach(n => {
          if (!posMemory.current[n.id] && tempPositioned[n.id]) {
            posMemory.current[n.id] = tempPositioned[n.id];
          }
        });
        
        setTimeout(() => fitView({ padding: 0.2, duration: 800 }), 150);
      }
    }
    lastNodeCount.current = curr;
  }, [rawNodes, fitView]);

  const buildNodes = useCallback((): Node[] => {
    const childMap: Record<string, KnowledgeNode[]> = {};
    rawNodes.forEach(n => {
      if (n.parent_id) {
        childMap[n.parent_id] = childMap[n.parent_id] ?? [];
        childMap[n.parent_id].push(n);
      }
      if (n.parent_ids) {
        n.parent_ids.forEach(pid => {
          if (pid && pid !== n.parent_id) {
            childMap[pid] = childMap[pid] ?? [];
            if (!childMap[pid].find(c => c.id === n.id)) {
              childMap[pid].push(n);
            }
          }
        });
      }
    });

    return rawNodes
      .filter(n => {
        if (n.parent_id && collapsedIds.has(n.parent_id)) return false;
        return true;
      })
      .map(n => ({
        id: n.id,
        type: 'cortex',
        // PRIORITY: use DB coords only if nonzero (zero means uninitialized)
        position: (() => {
          const hasDb = typeof n.x === 'number' && typeof n.y === 'number' && (n.x !== 0 || n.y !== 0);
          if (hasDb) return { x: n.x!, y: n.y! };
          return posMemory.current[n.id] ?? { x: 0, y: 0 };
        })(),
        data: {
          node: { ...n, children: childMap[n.id] ?? [] },
          isSelected: n.id === selectedParentId,
          isSuggested: suggestedNodeIds.includes(n.id),
          onClick: onClickNode,
        },
      }));
  }, [rawNodes, selectedParentId, suggestedNodeIds, onClickNode, collapsedIds]);

  const buildEdges = useCallback((): Edge[] => {
    const edgeSet = new Set<string>();
    const result: Edge[] = [];
    
    // Build edges from parent_id
    rawNodes.filter(n => n.parent_id && !collapsedIds.has(n.parent_id)).forEach(n => {
      const edgeId = `e-${n.parent_id}-${n.id}`;
      if (!edgeSet.has(edgeId)) {
        edgeSet.add(edgeId);
        const C = DEPTH_COLORS[n.depth % 4];
        const isNew = suggestedNodeIds.includes(n.id);
        result.push({
          id: edgeId,
          source: n.parent_id!,
          target: n.id,
          style: { stroke: isNew ? '#22d3ee' : `${C.border}55`, strokeWidth: isNew ? 2 : 1.5 },
          animated: n.id === selectedParentId || isNew,
        });
      }
    });
    
    // Build edges from edges table (many-to-one)
    edges.forEach(e => {
      const edgeId = `e-${e.source_id}-${e.target_id}`;
      if (!edgeSet.has(edgeId)) {
        edgeSet.add(edgeId);
        const targetNode = rawNodes.find(n => n.id === e.target_id);
        const C = targetNode ? DEPTH_COLORS[targetNode.depth % 4] : DEPTH_COLORS[0];
        const isNew = suggestedNodeIds.includes(e.target_id);
        result.push({
          id: edgeId,
          source: e.source_id,
          target: e.target_id,
          style: { stroke: isNew ? '#22d3ee' : `${C.border}55`, strokeWidth: isNew ? 2 : 1.5 },
          animated: e.target_id === selectedParentId || isNew,
        });
      }
    });
    
    return result;
  }, [rawNodes, edges, selectedParentId, suggestedNodeIds]);

  const [nodes, setNodes, onNodesChange] = useNodesState(buildNodes());
  const [edgesState, setEdges, onEdgesChange] = useEdgesState(buildEdges());

  useEffect(() => {
    setNodes(prev => {
      // Save current positions before rebuilding
      prev.forEach(n => { posMemory.current[n.id] = n.position; });
      return buildNodes();
    });
    setEdges(buildEdges());
  }, [rawNodes, edges, selectedParentId, suggestedNodeIds, buildNodes, buildEdges, collapsedIds]);


  // update both memory and database when dragging finishes
  const onNodeDragStop = useCallback(async (event: any, node: Node) => {
    // update memory immediately for snappy UI
    posMemory.current[node.id] = node.position;

    // persist to backend so position survives workspace switches
    try {
      await fetch(`http://localhost:8000/nodes/${node.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: sessionId,
          x: node.position.x,
          y: node.position.y,
        }),
      });
    } catch (err) {
      console.error('Failed to save node position:', err);
    }
  }, [sessionId]);
  const handleConnect = useCallback((connection: Connection) => {
    if (!connection.source || !connection.target) return;
    if (connection.source === connection.target) return;
    
    setEdges(eds => addEdge({
      ...connection,
      id: `e-${connection.source}-${connection.target}`,
      style: { stroke: '#22d3ee', strokeWidth: 2 },
      animated: true,
    }, eds));
    
    onEdgeConnect(connection.source, connection.target);
    setTimeout(() => fitView({ padding: 0.2, duration: 600 }), 300);
  }, [setEdges, onEdgeConnect, fitView]);

  const flowInputRef = useRef<HTMLInputElement>(null);
  const showFlowSuggestions = suggestions.length > 0 && !suggestDismissed && !flowSelectedParent;

  return (
    <div style={{ width: '100%', height: '100%' }}>
      <ReactFlow
        nodes={nodes} 
        edges={edgesState}
        onNodesChange={onNodesChange}
        onNodeDragStop={onNodeDragStop}
        onEdgesChange={onEdgesChange}
        onConnect={handleConnect}
        nodeTypes={nodeTypes}
        fitView 
        fitViewOptions={{ padding: 0.2, maxZoom: 1.2 }}
        minZoom={0.08} 
        maxZoom={2.5}
        style={{ background: 'transparent' }}
        proOptions={{ hideAttribution: true }}
        connectOnClick={false}
        snapToGrid={true}
        snapGrid={[20, 20]}
      >
        <Background color="rgba(168,85,247,.05)" gap={52} size={1} />
        <Controls style={{ background: 'rgba(8,8,14,.9)', border: '1px solid rgba(168,85,247,.2)', borderRadius: '12px', position: 'absolute', top: '60px', right: '16px', bottom: 'auto', left: 'auto' }} />
        <MiniMap
          style={{ background: 'rgba(8,8,14,.9)', border: '1px solid rgba(168,85,247,.15)', borderRadius: '12px' }}
          nodeColor={n => { const depth = (n.data as { node: KnowledgeNode }).node?.depth ?? 0; return DEPTH_COLORS[depth % 4].dot; }}
          maskColor="rgba(4,4,8,.7)"
        />
      </ReactFlow>

      {/* Floating header */}
      <div style={{ position: 'absolute', top: 0, left: 0, right: 0, padding: '14px 20px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', zIndex: 20, background: 'linear-gradient(to bottom,rgba(6,6,8,.9),transparent)', pointerEvents: 'none' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px', pointerEvents: 'all' }}>
          <h1 style={{ fontFamily: "'Syne',sans-serif", fontSize: '1.3rem', fontWeight: 800, background: 'linear-gradient(135deg,#a855f7 0%,#06b6d4 55%,#818cf8 100%)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent', letterSpacing: '-0.04em', lineHeight: 1 }}>CORTEX OS</h1>
          <span style={{ color: 'rgba(168,85,247,.4)', fontSize: '9px' }}>◆</span>
          <span style={{ color: 'rgba(148,163,184,.5)', fontSize: '11px', fontFamily: "'JetBrains Mono',monospace" }}>{activeSessionName}</span>
          <span style={{ color: 'rgba(148,163,184,.2)', fontSize: '9px', letterSpacing: '.15em', fontFamily: "'JetBrains Mono',monospace" }}>— {rawNodes.length} nodes</span>
        </div>
        <div style={{ display: 'flex', gap: '6px', pointerEvents: 'all' }}>
          {(['list', 'flow', 'search', 'firehose'] as AppMode[]).map(m => {
            const labels: Record<AppMode, string> = { list: '◈ List', flow: '⬡ Flow', search: '⌖ Search', firehose: '⚡ Firehose' };
            const colors: Record<AppMode, string> = { list: '#a855f7', flow: '#22d3ee', search: '#06b6d4', firehose: '#f59e0b' };
            const active = mode === m;
            return <button key={m} onClick={() => setMode(m)} style={{ background: active ? `${colors[m]}18` : 'rgba(6,6,8,.75)', border: `1px solid ${active ? colors[m] + '50' : 'rgba(255,255,255,.08)'}`, fontFamily: "'JetBrains Mono',monospace", fontSize: '10px', fontWeight: 700, letterSpacing: '.18em', textTransform: 'uppercase', padding: '6px 14px', borderRadius: '8px', cursor: 'pointer', color: active ? colors[m] : 'rgba(148,163,184,.45)', backdropFilter: 'blur(12px)', transition: 'all .2s' }}>{labels[m]}</button>;
          })}
          <button onClick={onRequestArrange} style={{ background: showArrangePanel ? 'rgba(245,158,11,.18)' : 'rgba(6,6,8,.75)', border: `1px solid ${showArrangePanel ? 'rgba(245,158,11,.5)' : 'rgba(255,255,255,.08)'}`, fontFamily: "'JetBrains Mono',monospace", fontSize: '10px', fontWeight: 700, letterSpacing: '.18em', textTransform: 'uppercase', padding: '6px 14px', borderRadius: '8px', cursor: 'pointer', color: showArrangePanel ? '#f59e0b' : 'rgba(148,163,184,.45)', backdropFilter: 'blur(12px)', transition: 'all .2s' }}>⚙ Arrange</button>
        </div>
      </div>

      {/* Floating bottom input bar */}
      <div style={{ position: 'absolute', bottom: 0, left: 0, right: 0, zIndex: 20, background: 'rgba(6,6,10,.92)', backdropFilter: 'blur(24px)', borderTop: '1px solid rgba(34,211,238,.1)', boxShadow: '0 -20px 60px rgba(0,0,0,.6)' }}>
        <div style={{ maxWidth: '860px', margin: '0 auto', padding: '14px 20px 22px' }}>
          {showFlowSuggestions && (
            <div style={{ background: 'rgba(6,6,10,.97)', border: '1px solid rgba(34,211,238,.2)', borderRadius: '14px', padding: '12px 14px', marginBottom: '10px', backdropFilter: 'blur(20px)', boxShadow: '0 0 30px rgba(34,211,238,.08)', animation: 'traySlideUp .25s cubic-bezier(.16,1,.3,1)' }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '8px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <div style={{ width: '6px', height: '6px', borderRadius: '50%', background: '#22d3ee', boxShadow: '0 0 6px #22d3ee', animation: 'pulse 1.5s ease infinite' }} />
                  <span style={{ color: 'rgba(34,211,238,.7)', fontSize: '9px', letterSpacing: '.2em', textTransform: 'uppercase', fontFamily: "'JetBrains Mono',monospace" }}>Semantic connections — nodes highlighted in graph</span>
                </div>
                <button onClick={() => setSuggestDismissed(true)} style={{ color: 'rgba(148,163,184,.3)', background: 'none', border: 'none', fontSize: '9px', fontFamily: "'JetBrains Mono',monospace", letterSpacing: '.06em', textTransform: 'uppercase', cursor: 'pointer' }}>[dismiss]</button>
              </div>
              <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                {suggestions.slice(0, 3).map(n => {
                  const pct = n.similarity ? Math.round(n.similarity * 100) : null;
                  const C = DEPTH_COLORS[n.depth % 4];
                  return (
                    <div key={n.id} onClick={() => { setFlowSelectedParent(n); setSuggestDismissed(true); flowInputRef.current?.focus(); }}
                      style={{ flex: 1, minWidth: '140px', background: `${C.glow}`, border: `1px solid ${C.border}40`, borderRadius: '10px', padding: '8px 12px', cursor: 'pointer', transition: 'all .2s', overflow: 'hidden' }}
                      onMouseEnter={e => { (e.currentTarget as HTMLDivElement).style.borderColor = C.border; }}
                      onMouseLeave={e => { (e.currentTarget as HTMLDivElement).style.borderColor = `${C.border}40`; }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '4px' }}>
                        <span style={{ color: C.text, fontSize: '8px', letterSpacing: '.12em', textTransform: 'uppercase' }}>Branch from →</span>
                        {pct && <span style={{ color: C.text, fontSize: '8px', background: `${C.border}20`, borderRadius: '4px', padding: '1px 5px' }}>{pct}%</span>}
                      </div>
                      <p style={{ color: '#c4cad4', fontSize: '11px', lineHeight: '1.4', margin: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontFamily: "'JetBrains Mono',monospace" }}>{n.content}</p>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
          {flowSelectedParent && (
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', background: 'rgba(34,211,238,.06)', border: '1px solid rgba(34,211,238,.18)', borderRadius: '12px', padding: '10px 16px', marginBottom: '12px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '12px', minWidth: 0 }}>
                <span style={{ color: '#22d3ee', fontSize: '9px', letterSpacing: '.1em', textTransform: 'uppercase', flexShrink: 0, fontFamily: "'JetBrains Mono',monospace" }}>Branch from</span>
                <span style={{ color: 'rgba(148,163,184,.6)', fontSize: '11px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontFamily: "'JetBrains Mono',monospace" }}>{flowSelectedParent.content.slice(0, 80)}{flowSelectedParent.content.length > 80 ? '…' : ''}</span>
              </div>
              <button onClick={() => setFlowSelectedParent(null)} style={{ color: 'rgba(148,163,184,.3)', fontSize: '9px', background: 'none', border: 'none', flexShrink: 0, marginLeft: '12px', fontFamily: "'JetBrains Mono',monospace", letterSpacing: '.06em', textTransform: 'uppercase', cursor: 'pointer' }}>[ESC]</button>
            </div>
          )}
          <form onSubmit={handleFlowSubmit} style={{ display: 'flex', gap: '10px' }}>
            <input ref={flowInputRef} type="text" value={flowContent} onChange={e => handleFlowContentChange(e.target.value)}
              placeholder={flowSelectedParent ? 'Add sub-thought...' : 'Capture thought in graph...'}
              style={{ flex: 1, background: 'rgba(255,255,255,.04)', border: '1px solid rgba(34,211,238,.15)', borderRadius: '14px', padding: '14px 18px', color: '#e2e8f0', fontSize: '13px', fontFamily: "'JetBrains Mono',monospace", transition: 'border-color .2s', outline: 'none' }}
              onFocus={e => (e.target.style.borderColor = 'rgba(34,211,238,.45)')}
              onBlur={e => (e.target.style.borderColor = 'rgba(34,211,238,.15)')} />
            <button type="submit" disabled={submitting || !flowContent.trim()} style={{ padding: '14px 24px', borderRadius: '14px', border: 'none', background: (!submitting && flowContent.trim()) ? 'linear-gradient(135deg,#22d3ee,#06b6d4)' : 'rgba(34,211,238,.1)', color: (!submitting && flowContent.trim()) ? '#060608' : 'rgba(34,211,238,.3)', fontSize: '11px', fontFamily: "'JetBrains Mono',monospace", fontWeight: 700, letterSpacing: '.1em', textTransform: 'uppercase', boxShadow: (!submitting && flowContent.trim()) ? '0 0 24px rgba(34,211,238,.3)' : 'none', cursor: (submitting || !flowContent.trim()) ? 'not-allowed' : 'pointer', transition: 'all .2s' }}>{submitting ? '···' : 'EXEC'}</button>
          </form>
        </div>
      </div>
    </div>
  );
}

function GraphFlow(props: GraphFlowInnerProps) {
  return (
    <ReactFlowProvider>
      <GraphFlowInner {...props} />
    </ReactFlowProvider>
  );
}
// ── Types Update (Ensure this is in your types section) ──
interface EdgeData { id: string; source: string; target: string; session_id: string; }

// ── Main Page (COMPLETED WITH ALL FIXES) ───────────────────────────────────────────────
export default function Home() {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [activeSession, setActiveSession] = useState<Session | null>(null);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [rawNodes, setRawNodes] = useState<KnowledgeNode[]>([]);
  const [rawEdges, setRawEdges] = useState<EdgeData[]>([]); // NEW: Store edges
  const [searchResults, setSearchResults] = useState<KnowledgeNode[]>([]);
  const [suggestions, setSuggestions] = useState<KnowledgeNode[]>([]);
  const [suggestDismissed, setSuggestDismissed] = useState(false);
  const [flowContent, setFlowContent] = useState('');
  const [flowSelectedParent, setFlowSelectedParent] = useState<KnowledgeNode | null>(null);
  const [flowSuggestions, setFlowSuggestions] = useState<KnowledgeNode[]>([]);
  const [flowSuggestDismissed, setFlowSuggestDismissed] = useState(false);
  const [suggestedNodeIds, setSuggestedNodeIds] = useState<string[]>([]);
  const [synthesisNode, setSynthesisNode] = useState<KnowledgeNode | null>(null);
  const [expandNode, setExpandNode] = useState<KnowledgeNode | null>(null);
  const [flowPopupNode, setFlowPopupNode] = useState<KnowledgeNode | null>(null);
  const [content, setContent] = useState('');
  const [searchQuery, setSearchQuery] = useState('');
  const [mode, setMode] = useState<AppMode>('list');
  const [selectedParent, setSelectedParent] = useState<KnowledgeNode | null>(null);
  const [loading, setLoading] = useState(false);
  const [fetchError, setFetchError] = useState(false);
  const [searching, setSearching] = useState(false);
  const [newNodeId, setNewNodeId] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [savedSyntheses, setSavedSyntheses] = useState<SavedSynthesis[]>([]);
  const [showSavedPanel, setShowSavedPanel] = useState(false);
  const [showArrangePanel, setShowArrangePanel] = useState(false);

  // collapse/expand tracking for folding branches
  const [collapsedIds, setCollapsedIds] = useState<Set<string>>(new Set());
  const toggleCollapse = useCallback((id: string) => {
    setCollapsedIds(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const inputRef = useRef<HTMLInputElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const suggestRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const flowSuggestRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const treeData = useMemo((): KnowledgeNode[] => {
    const map: Record<string, KnowledgeNode> = {};
    rawNodes.forEach(n => (map[n.id] = { ...n, children: [] }));
    const roots: KnowledgeNode[] = [];
    rawNodes.forEach(n => {
      const node = map[n.id];
      const primaryParent = n.parent_id && map[n.parent_id];
      if (primaryParent) {
        primaryParent.children!.push(node);
      } else {
        roots.push(node);
      }
    });
    return roots;
  }, [rawNodes, collapsedIds]);

  const loadSessions = useCallback(async () => {
    try { const r = await fetch('http://localhost:8000/sessions'); if (!r.ok) return []; const data: Session[] = await r.json(); setSessions(data); return data; } catch { return []; }
  }, []);
  
  useEffect(() => { (async () => { const data = await loadSessions(); if (data && data.length > 0) setActiveSession(data[0]); })(); }, [loadSessions]);

  const fetchNodes = useCallback(async (sessionId: string, retries = 3) => {
    setLoading(true); setFetchError(false);
    try {
      const r = await fetch(`http://localhost:8000/nodes?session_id=${sessionId}`);
      if (!r.ok) { if (retries > 0) { setTimeout(() => fetchNodes(sessionId, retries - 1), 1500); return; } setFetchError(true); return; }
      const data = await r.json();
      setRawNodes(data.nodes || data); 
      setRawEdges(data.edges || []); // NEW: Store many-to-one edges
    } catch { if (retries > 0) { setTimeout(() => fetchNodes(sessionId, retries - 1), 1500); return; } setFetchError(true); }
    finally { setLoading(false); }
  }, []);

  const fetchSavedSyntheses = useCallback(async (sessionId: string) => {
    try {
      const r = await fetch(`http://localhost:8000/synthesis/saved?session_id=${sessionId}`);
      if (r.ok) setSavedSyntheses(await r.json());
    } catch { }
  }, []);

  useEffect(() => {
    if (activeSession) {
      setRawNodes([]); setRawEdges([]); setSelectedParent(null); setContent('');
      setSuggestions([]); setFlowContent(''); setFlowSelectedParent(null);
      setFlowSuggestions([]); setSuggestedNodeIds([]);
      setShowArrangePanel(false);
      fetchNodes(activeSession.id);
      fetchSavedSyntheses(activeSession.id);
    }
  }, [activeSession, fetchNodes, fetchSavedSyntheses]);

  // UI Handlers (Claude Fixes)
  const handleCreateSession = async (name: string) => { try { const r = await fetch('http://localhost:8000/sessions', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name }) }); if (!r.ok) return; const s: Session = await r.json(); setSessions(p => [...p, s]); setActiveSession(s); } catch { } };
  const handleRenameSession = async (id: string, name: string) => { try { await fetch(`http://localhost:8000/sessions/${id}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name }) }); setSessions(p => p.map(s => s.id === id ? { ...s, name } : s)); if (activeSession?.id === id) setActiveSession(p => p ? { ...p, name } : p); } catch { } };
  const handleDeleteSession = async (id: string) => { try { await fetch(`http://localhost:8000/sessions/${id}`, { method: 'DELETE' }); const rem = sessions.filter(s => s.id !== id); setSessions(rem); if (activeSession?.id === id) setActiveSession(rem[0] ?? null); } catch { } };

  const handleSearch = useCallback((val: string) => {
    setSearchQuery(val); if (debounceRef.current) clearTimeout(debounceRef.current);
    if (val.trim().length < 2 || !activeSession) { setSearchResults([]); setSearching(false); return; }
    setSearching(true);
    debounceRef.current = setTimeout(async () => {
      try { const r = await fetch(`http://localhost:8000/search?query=${encodeURIComponent(val)}&session_id=${activeSession.id}&limit=8`); if (!r.ok) throw new Error(); setSearchResults(await r.json()); }
      catch { setSearchResults([]); } finally { setSearching(false); }
    }, 400);
  }, [activeSession]);

  const runSemanticSuggest = useCallback(async (val: string, sessionId: string, onResult: (nodes: KnowledgeNode[]) => void) => {
    if (val.trim().length < 3) { onResult([]); return; }
    const words = val.trim().split(/\s+/);
    const queryStr = words.slice(-8).join(' ');
    try {
      const r = await fetch(`http://localhost:8000/search?query=${encodeURIComponent(queryStr)}&session_id=${sessionId}&limit=6`);
      if (!r.ok) return;
      const res: KnowledgeNode[] = await r.json();
      const boosted = res.map(n => ({ ...n, similarity: (n.similarity ?? 0) + (n.depth === 0 ? 0.05 : 0) }))
        .filter(n => (n.similarity ?? 0) > 0.005).sort((a, b) => (b.similarity ?? 0) - (a.similarity ?? 0)).slice(0, 3);
      onResult(boosted);
    } catch { onResult([]); }
  }, []);

  const handleContentChange = useCallback((val: string) => {
    setContent(val); setSuggestDismissed(false); if (suggestRef.current) clearTimeout(suggestRef.current);
    if (val.trim().length < 3 || selectedParent || !activeSession) { setSuggestions([]); return; }
    suggestRef.current = setTimeout(() => runSemanticSuggest(val, activeSession.id, setSuggestions), 400);
  }, [selectedParent, activeSession, runSemanticSuggest]);

  const handleFlowContentChange = useCallback((val: string) => {
    setFlowContent(val); setFlowSuggestDismissed(false); if (flowSuggestRef.current) clearTimeout(flowSuggestRef.current);
    if (val.trim().length < 3 || !activeSession) { setFlowSuggestions([]); setSuggestedNodeIds([]); return; }
    flowSuggestRef.current = setTimeout(() => {
      runSemanticSuggest(val, activeSession.id, (nodes) => { setFlowSuggestions(nodes); setSuggestedNodeIds(nodes.map(n => n.id)); });
    }, 400);
  }, [activeSession, runSemanticSuggest]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault(); if (!content.trim() || submitting || !activeSession) return; setSubmitting(true); setSuggestions([]);
    try {
      const r = await fetch('http://localhost:8000/nodes', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ content, parent_id: selectedParent?.id ?? null, depth: selectedParent ? selectedParent.depth + 1 : 0, session_id: activeSession.id }) });
      if (!r.ok) throw new Error();
      const data = await r.json();
      // handle regular node creation vs url-import acknowledgment
      if (data.node) {
        setNewNodeId(data.node.id);
      } else if (data.message) {
        // url import was scheduled; maybe show a toast later
        console.log('URL import scheduled');
      }
      setContent(''); setSelectedParent(null);
      await fetchNodes(activeSession.id); setTimeout(() => setNewNodeId(null), 1000);
    } catch (err) { console.error(err); } finally { setSubmitting(false); inputRef.current?.focus(); }
  };

  const handleFlowSubmit = useCallback(async (e: React.FormEvent) => {
    e.preventDefault(); if (!flowContent.trim() || submitting || !activeSession) return; setSubmitting(true);
    setFlowSuggestions([]); setSuggestedNodeIds([]);
    try {
      const r = await fetch('http://localhost:8000/nodes', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: flowContent, parent_id: flowSelectedParent?.id ?? null, depth: flowSelectedParent ? flowSelectedParent.depth + 1 : 0, session_id: activeSession.id }),
      });
      if (!r.ok) throw new Error(); const { node } = await r.json();
      setNewNodeId(node.id); setFlowContent(''); setFlowSelectedParent(null);
      await fetchNodes(activeSession.id); setTimeout(() => setNewNodeId(null), 1000);
    } catch (err) { console.error(err); } finally { setSubmitting(false); }
  }, [flowContent, flowSelectedParent, activeSession, submitting, fetchNodes]);

  const handleDeleteNode = useCallback(async (node: KnowledgeNode) => {
    if (!activeSession) return;
    const countDesc = (n: KnowledgeNode): number => (n.children?.length ?? 0) + (n.children?.reduce((s, c) => s + countDesc(c), 0) ?? 0);
    const descCount = countDesc(node);
    const msg = descCount > 0 ? `Delete "${node.content.slice(0, 60)}…" and its ${descCount} descendant${descCount !== 1 ? 's' : ''}?` : `Delete "${node.content.slice(0, 60)}"?`;
    if (!confirm(msg)) return;
    try {
      const r = await fetch(`http://localhost:8000/nodes/${node.id}?session_id=${activeSession.id}`, { method: 'DELETE' });
      if (!r.ok) { console.error('Delete failed', await r.text()); return; }
      await fetchNodes(activeSession.id);
    } catch (err) { console.error('Delete error', err); }
  }, [activeSession, fetchNodes]);

  const handleDetachNode = useCallback(async (node: KnowledgeNode) => {
    if (!activeSession) return;
    try {
      const r = await fetch(`http://localhost:8000/nodes/${node.id}/detach`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: activeSession.id }),
      });
      if (!r.ok) { console.error('Detach failed', await r.text()); return; }
      await fetchNodes(activeSession.id);
    } catch (err) { console.error('Detach error', err); }
  }, [activeSession, fetchNodes]);

  const handleEdgeConnect = useCallback(async (parentId: string, childId: string) => {
    if (!activeSession) return;
    const parentNode = rawNodes.find(n => n.id === parentId);
    if (!parentNode) return;
    try {
      const r = await fetch(`http://localhost:8000/nodes/${childId}`, {
        method: 'PATCH', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ parent_id: parentId, depth: parentNode.depth + 1, session_id: activeSession.id }),
      });
      if (!r.ok) { console.error('Reparent failed', await r.text()); }
      await fetchNodes(activeSession.id);
    } catch (err) { console.error('Reparent error', err); }
  }, [activeSession, rawNodes, fetchNodes]);

  const handleApplyArrangement = useCallback(async (sourceId: string, targetParentId: string | null) => {
    if (!activeSession) return;
    const parentNode = targetParentId ? rawNodes.find(n => n.id === targetParentId) : null;
    const newDepth = parentNode ? parentNode.depth + 1 : 0;
    try {
      const r = await fetch(`http://localhost:8000/nodes/${sourceId}`, {
        method: 'PATCH', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ parent_id: targetParentId, depth: newDepth, session_id: activeSession.id }),
      });
      if (!r.ok) console.error('Arrangement failed');
      await fetchNodes(activeSession.id);
    } catch (err) { console.error(err); }
  }, [activeSession, rawNodes, fetchNodes]);

  const handleFlowBranch = useCallback((node: KnowledgeNode) => { setFlowSelectedParent(node); }, []);

  const sW = sidebarCollapsed ? 52 : 240;
  const stats = [{ label: 'Nodes', value: rawNodes.length }, { label: 'Roots', value: treeData.length }, { label: 'Depth', value: rawNodes.reduce((m, n) => Math.max(m, n.depth), 0) }];
  const showSuggestions = suggestions.length > 0 && !suggestDismissed && !selectedParent;

  return (<>
    <style>{`
      @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400;500;700&family=Syne:wght@800&display=swap');
      *,*::before,*::after{box-sizing:border-box;margin:0;padding:0;}body{background:#060608;overflow-x:hidden;}
      .grid-bg{background-image:linear-gradient(rgba(168,85,247,.035) 1px,transparent 1px),linear-gradient(90deg,rgba(168,85,247,.035) 1px,transparent 1px);background-size:52px 52px;}
      @keyframes nodeAppear{from{opacity:0;transform:translateY(-10px) scale(.97);}to{opacity:1;transform:translateY(0) scale(1);}}
      @keyframes traySlideUp{from{opacity:0;transform:translateY(8px);}to{opacity:1;transform:translateY(0);}}
      @keyframes scan{from{transform:translateY(-100%);}to{transform:translateY(100vh);}}
      @keyframes spin{to{transform:rotate(360deg);}}
      @keyframes pulse{0%,100%{opacity:.4;}50%{opacity:1;}}
      @keyframes fadeIn{from{opacity:0;transform:translateY(6px);}to{opacity:1;transform:translateY(0);}}
      @keyframes suggestPulse{0%,100%{box-shadow:0 0 0 2px rgba(34,211,238,.3),0 0 24px rgba(34,211,238,.15);}50%{box-shadow:0 0 0 3px rgba(34,211,238,.6),0 0 40px rgba(34,211,238,.35);}}
      ::-webkit-scrollbar{width:3px;}::-webkit-scrollbar-thumb{background:rgba(168,85,247,.3);border-radius:2px;}
      input,select{outline:none;}input::placeholder{color:rgba(148,163,184,.2);}
      .mode-btn{background:none;border:1px solid transparent;font-family:'JetBrains Mono',monospace;font-size:10px;font-weight:700;letter-spacing:.18em;text-transform:uppercase;padding:6px 14px;border-radius:8px;transition:all .2s;cursor:pointer;}
      .react-flow__controls button{background:rgba(8,8,14,.9)!important;border-color:rgba(168,85,247,.2)!important;color:#a855f7!important;fill:#a855f7!important;}
      .react-flow__controls button:hover{background:rgba(168,85,247,.15)!important;}
      .react-flow__edge-path{transition:stroke .3s;}
      .react-flow__controls{bottom:auto!important;top:60px!important;right:16px!important;left:auto!important;}
    `}</style>

    {synthesisNode && activeSession && (
      <SynthesisOverlay
        node={synthesisNode}
        sessionId={activeSession.id}
        onClose={() => setSynthesisNode(null)}
        onSaved={s => { setSavedSyntheses(p => [...p, s]); setShowSavedPanel(true); }}
      />
    )}
    {expandNode && activeSession && <ExpandOverlay node={expandNode} sessionId={activeSession.id} onClose={() => setExpandNode(null)} onDone={() => { setExpandNode(null); fetchNodes(activeSession.id); }} />}
    {flowPopupNode && activeSession && (
      <FlowNodePopup
        node={flowPopupNode}
        onBranch={n => { handleFlowBranch(n); setFlowPopupNode(null); }}
        onSynthesize={n => { setSynthesisNode(n); setFlowPopupNode(null); }}
        onExpand={n => { setExpandNode(n); setFlowPopupNode(null); }}
        onDetach={n => { handleDetachNode(n); setFlowPopupNode(null); }}
        onDelete={n => { handleDeleteNode(n); setFlowPopupNode(null); }}
        onClose={() => setFlowPopupNode(null)}
      />
    )}

    <Sidebar sessions={sessions} activeId={activeSession?.id ?? null}
      onSelect={s => { setActiveSession(s); }}
      onCreate={handleCreateSession} onRename={handleRenameSession} onDelete={handleDeleteSession}
      collapsed={sidebarCollapsed} onToggle={() => setSidebarCollapsed(p => !p)}
    />

    <div className="grid-bg" style={{ minHeight: '100vh', marginLeft: `${sW}px`, transition: 'margin-left .25s cubic-bezier(.16,1,.3,1)', fontFamily: "'JetBrains Mono',monospace", color: '#e2e8f0' }}>
      <div style={{ position: 'fixed', top: 0, left: sW, right: 0, height: '2px', zIndex: 50, background: 'linear-gradient(90deg,transparent,rgba(168,85,247,.35),transparent)', animation: 'scan 7s linear infinite', pointerEvents: 'none', transition: 'left .25s' }} />
      <div style={{ position: 'fixed', top: '-10%', left: '30%', width: '500px', height: '500px', background: 'radial-gradient(circle,rgba(168,85,247,.07) 0%,transparent 65%)', filter: 'blur(60px)', pointerEvents: 'none', zIndex: 0 }} />

      {/* ── Flow view ── */}
      {mode === 'flow' && activeSession && !loading && !fetchError && (
        <div style={{ position: 'fixed', top: 0, left: sW, right: 0, bottom: 0, zIndex: 10, transition: 'left .25s' }}>
          {rawNodes.length === 0 ? (
            <div style={{ width: '100%', height: '100%', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: '16px' }}>
              <p style={{ color: 'rgba(148,163,184,.15)', fontSize: '11px', letterSpacing: '.3em', textTransform: 'uppercase' }}>Empty workspace — add your first node below</p>
            </div>
          ) : (
            <>
              {showArrangePanel && (
                <div style={{ position: 'absolute', top: '60px', left: '16px', width: '380px', zIndex: 30, maxHeight: 'calc(100vh - 200px)', overflowY: 'auto' }}>
                  <ArrangePanel
                    sessionId={activeSession.id}
                    onApply={handleApplyArrangement}
                    onClose={() => setShowArrangePanel(false)}
                  />
                </div>
              )}
              <GraphFlow
                rawNodes={rawNodes}
                edges={rawEdges}
                treeData={treeData}
                sessionId={activeSession.id}
                selectedParentId={flowSelectedParent?.id ?? null}
                suggestedNodeIds={suggestedNodeIds}
                onClickNode={setFlowPopupNode}
                onEdgeConnect={handleEdgeConnect}
                onEdgeDetach={handleDetachNode}
                onNewNode={async () => { }}
                onSetSelectedParent={setFlowSelectedParent}
                synthesisNode={synthesisNode}
                setSynthesisNode={setSynthesisNode}
                setExpandNode={setExpandNode}
                handleDeleteNode={handleDeleteNode}
                sidebarWidth={sW}
                activeSessionName={activeSession.name}
                mode={mode}
                setMode={setMode}
                collapsedIds={collapsedIds}
                suggestions={flowSuggestions}
                suggestDismissed={flowSuggestDismissed}
                setSuggestDismissed={setFlowSuggestDismissed}
                flowContent={flowContent}
                setFlowContent={setFlowContent}
                flowSelectedParent={flowSelectedParent}
                setFlowSelectedParent={setFlowSelectedParent}
                submitting={submitting}
                handleFlowSubmit={handleFlowSubmit}
                handleFlowContentChange={handleFlowContentChange}
                onRequestArrange={() => setShowArrangePanel(p => !p)}
                showArrangePanel={showArrangePanel}
              />
            </>
          )}
        </div>
      )}

      {/* ── Non-Flow views ── */}
      {mode !== 'flow' && (
        <div style={{ maxWidth: '900px', margin: '0 auto', padding: '32px 24px 80px', position: 'relative', zIndex: 1 }}>

          {/* Header */}
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '32px', flexWrap: 'wrap', gap: '16px' }}>
            <div>
              <h1 style={{ fontFamily: "'Syne',sans-serif", fontSize: 'clamp(1.5rem,4vw,2.2rem)', fontWeight: 800, background: 'linear-gradient(135deg,#a855f7 0%,#06b6d4 55%,#818cf8 100%)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent', letterSpacing: '-0.04em', lineHeight: 1, marginBottom: '6px' }}>CORTEX OS</h1>
              {activeSession && <p style={{ color: 'rgba(148,163,184,.4)', fontSize: '11px', fontFamily: "'JetBrains Mono',monospace", letterSpacing: '.12em' }}>◈ {activeSession.name}</p>}
            </div>
            <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
              {(['list', 'flow', 'search', 'firehose'] as AppMode[]).map(m => {
                const labels: Record<AppMode, string> = { list: '◈ List', flow: '⬡ Flow', search: '⌖ Search', firehose: '⚡ Firehose' };
                const colors: Record<AppMode, string> = { list: '#a855f7', flow: '#22d3ee', search: '#06b6d4', firehose: '#f59e0b' };
                const active = mode === m;
                return (
                  <button key={m} onClick={() => setMode(m)} style={{ background: active ? `${colors[m]}18` : 'rgba(6,6,8,.75)', border: `1px solid ${active ? colors[m] + '50' : 'rgba(255,255,255,.1)'}`, fontFamily: "'JetBrains Mono',monospace", fontSize: '10px', fontWeight: 700, letterSpacing: '.18em', textTransform: 'uppercase', padding: '8px 16px', borderRadius: '10px', cursor: 'pointer', color: active ? colors[m] : 'rgba(148,163,184,.45)', backdropFilter: 'blur(12px)', transition: 'all .2s' }}>{labels[m]}</button>
                );
              })}
            </div>
          </div>

          {/* ── List mode ── */}
          {mode === 'list' && activeSession && (
            <>
              {/* Stats bar */}
              {rawNodes.length > 0 && (
                <div style={{ display: 'flex', gap: '10px', marginBottom: '28px', flexWrap: 'wrap' }}>
                  {stats.map(s => (
                    <div key={s.label} style={{ background: 'rgba(168,85,247,.06)', border: '1px solid rgba(168,85,247,.15)', borderRadius: '12px', padding: '10px 18px', display: 'flex', alignItems: 'center', gap: '10px' }}>
                      <span style={{ color: '#a855f7', fontSize: '18px', fontWeight: 700, fontFamily: "'Syne',sans-serif" }}>{s.value}</span>
                      <span style={{ color: 'rgba(148,163,184,.4)', fontSize: '9px', letterSpacing: '.2em', textTransform: 'uppercase' }}>{s.label}</span>
                    </div>
                  ))}
                  {savedSyntheses.filter(s => s.session_id === activeSession.id).length > 0 && (
                    <button onClick={() => setShowSavedPanel(p => !p)} style={{ background: showSavedPanel ? 'rgba(34,211,238,.1)' : 'rgba(34,211,238,.04)', border: `1px solid ${showSavedPanel ? 'rgba(34,211,238,.3)' : 'rgba(34,211,238,.12)'}`, borderRadius: '12px', padding: '10px 18px', display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer', transition: 'all .2s' }}>
                      <span style={{ fontSize: '13px' }}>🔒</span>
                      <span style={{ color: showSavedPanel ? '#22d3ee' : 'rgba(34,211,238,.5)', fontSize: '9px', letterSpacing: '.2em', textTransform: 'uppercase' }}>Saved ({savedSyntheses.filter(s => s.session_id === activeSession.id).length})</span>
                    </button>
                  )}
                  <button onClick={() => setShowArrangePanel(p => !p)} style={{ background: showArrangePanel ? 'rgba(245,158,11,.1)' : 'rgba(245,158,11,.04)', border: `1px solid ${showArrangePanel ? 'rgba(245,158,11,.3)' : 'rgba(245,158,11,.12)'}`, borderRadius: '12px', padding: '10px 18px', display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer', transition: 'all .2s' }}>
                    <span style={{ color: showArrangePanel ? '#f59e0b' : 'rgba(245,158,11,.5)', fontSize: '9px', letterSpacing: '.2em', textTransform: 'uppercase' }}>⚙ AI Arrange</span>
                  </button>
                </div>
              )}

              {showSavedPanel && (
                <SavedSynthesesPanel
                  sessionId={activeSession.id}
                  savedSyntheses={savedSyntheses}
                  onDelete={async id => {
                    try {
                      await fetch(`http://localhost:8000/synthesis/saved/${id}`, { method: 'DELETE' });
                      setSavedSyntheses(p => p.filter(s => s.id !== id));
                    } catch { }
                  }}
                  onClose={() => setShowSavedPanel(false)}
                />
              )}

              {showArrangePanel && rawNodes.length >= 3 && (
                <ArrangePanel
                  sessionId={activeSession.id}
                  onApply={handleApplyArrangement}
                  onClose={() => setShowArrangePanel(false)}
                />
              )}

              {/* Tree with bottom padding for fixed input bar */}
              {!loading && !fetchError && treeData.length > 0 && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '16px', animation: 'fadeIn .4s ease', paddingBottom: '120px' }}>
                  {treeData.map(node => (
                    <NodeCard
                      key={node.id}
                      node={node}
                      onBranch={n => { setSelectedParent(n); setTimeout(() => inputRef.current?.focus(), 50); }}
                      onSynthesize={n => setSynthesisNode(n)}
                      onExpand={n => setExpandNode(n)}
                      onDelete={handleDeleteNode}
                      selectedId={selectedParent?.id ?? null}
                      isNew={node.id === newNodeId}
                      collapsedIds={collapsedIds}
                      toggleCollapse={toggleCollapse}
                    />
                  ))}
                </div>
              )}

              {loading && (
                <div style={{ display: 'flex', alignItems: 'center', gap: '12px', padding: '40px 0', justifyContent: 'center' }}>
                  <div style={{ width: '20px', height: '20px', borderRadius: '50%', border: '2px solid rgba(168,85,247,.3)', borderTopColor: '#a855f7', animation: 'spin .8s linear infinite' }} />
                  <span style={{ color: 'rgba(148,163,184,.3)', fontSize: '11px', letterSpacing: '.25em', textTransform: 'uppercase' }}>Loading nodes...</span>
                </div>
              )}
              {fetchError && !loading && (
                <div style={{ background: 'rgba(244,114,182,.05)', border: '1px solid rgba(244,114,182,.2)', borderRadius: '16px', padding: '24px', textAlign: 'center', marginBottom: '24px' }}>
                  <p style={{ color: 'rgba(244,114,182,.6)', fontSize: '12px', letterSpacing: '.15em', textTransform: 'uppercase', marginBottom: '12px' }}>Connection Error</p>
                  <button onClick={() => activeSession && fetchNodes(activeSession.id)} style={{ background: 'rgba(244,114,182,.1)', border: '1px solid rgba(244,114,182,.3)', borderRadius: '10px', padding: '8px 20px', color: '#f472b6', fontSize: '10px', fontFamily: "'JetBrains Mono',monospace", letterSpacing: '.1em', textTransform: 'uppercase', cursor: 'pointer' }}>↺ Retry</button>
                </div>
              )}
              {!loading && !fetchError && rawNodes.length === 0 && (
                <div style={{ textAlign: 'center', padding: '80px 0' }}>
                  <div style={{ width: '60px', height: '60px', borderRadius: '50%', border: '1px solid rgba(168,85,247,.2)', margin: '0 auto 24px', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                    <span style={{ color: 'rgba(168,85,247,.3)', fontSize: '24px' }}>◈</span>
                  </div>
                  <p style={{ color: 'rgba(148,163,184,.15)', fontSize: '11px', letterSpacing: '.3em', textTransform: 'uppercase' }}>Empty workspace — add your first thought above</p>
                </div>
              )}

              {/* Fixed input form at bottom */}
              <div style={{
                position: 'fixed',
                bottom: 0,
                left: sW,
                right: 0,
                background: 'rgba(6,6,10,0.85)',
                backdropFilter: 'blur(20px)',
                borderTop: '1px solid rgba(168,85,247,0.2)',
                padding: '20px 24px',
                zIndex: 100,
                transition: 'left .25s cubic-bezier(.16,1,.3,1)'
              }}>
                <div style={{ maxWidth: '860px', margin: '0 auto' }}>
                  {/* Branching indicator */}
                  {selectedParent && (
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', background: 'rgba(168,85,247,.06)', border: '1px solid rgba(168,85,247,.2)', borderRadius: '12px', padding: '10px 16px', marginBottom: '16px' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '12px', minWidth: 0 }}>
                        <span style={{ color: 'rgba(168,85,247,.6)', fontSize: '9px', letterSpacing: '.12em', textTransform: 'uppercase', flexShrink: 0 }}>Branching from</span>
                        <span style={{ color: 'rgba(148,163,184,.6)', fontSize: '11px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{selectedParent.content.slice(0, 70)}{selectedParent.content.length > 70 ? '…' : ''}</span>
                      </div>
                      <button onClick={() => { setSelectedParent(null); setSuggestions([]); }} style={{ color: 'rgba(148,163,184,.3)', fontSize: '9px', background: 'none', border: 'none', flexShrink: 0, marginLeft: '12px', fontFamily: "'JetBrains Mono',monospace", letterSpacing: '.06em', textTransform: 'uppercase', cursor: 'pointer' }}>[ESC]</button>
                    </div>
                  )}

                  {showSuggestions && (
                    <SuggestTray
                      suggestions={suggestions}
                      onAccept={n => { setSelectedParent(n); setSuggestions([]); setTimeout(() => inputRef.current?.focus(), 50); }}
                      onDismiss={() => setSuggestDismissed(true)}
                    />
                  )}

                  {/* Actual Form */}
                  <form onSubmit={handleSubmit} style={{ display: 'flex', gap: '12px' }}>
                    <input ref={inputRef} type="text" value={content} onChange={e => handleContentChange(e.target.value)} placeholder={selectedParent ? 'Add sub-thought...' : 'Capture thought or paste URL...'} style={{ flex: 1, background: 'rgba(255,255,255,.04)', border: '1px solid rgba(168,85,247,.2)', borderRadius: '14px', padding: '14px 18px', color: '#e2e8f0', fontSize: '13px', fontFamily: "'JetBrains Mono',monospace", transition: 'border-color .2s', outline: 'none' }}
                      onFocus={e => (e.target.style.borderColor = 'rgba(168,85,247,.5)')}
                      onBlur={e => (e.target.style.borderColor = 'rgba(168,85,247,.2)')} />
                    <button type="submit" disabled={submitting || !content.trim()} style={{ padding: '14px 28px', borderRadius: '14px', border: 'none', background: (!submitting && content.trim()) ? 'linear-gradient(135deg,#a855f7,#06b6d4)' : 'rgba(168,85,247,.1)', color: (!submitting && content.trim()) ? '#fff' : 'rgba(168,85,247,.3)', fontSize: '11px', fontFamily: "'JetBrains Mono',monospace", fontWeight: 700, letterSpacing: '.1em', textTransform: 'uppercase', boxShadow: (!submitting && content.trim()) ? '0 0 30px rgba(168,85,247,.4)' : 'none', cursor: (submitting || !content.trim()) ? 'not-allowed' : 'pointer', transition: 'all .2s', flexShrink: 0 }}>
                      {submitting ? <span style={{ display: 'flex', alignItems: 'center', gap: '6px' }}><span style={{ display: 'inline-block', width: '10px', height: '10px', borderRadius: '50%', border: '2px solid rgba(168,85,247,.4)', borderTopColor: '#a855f7', animation: 'spin .8s linear infinite' }} />Adding</span> : '+ EXEC'}
                    </button>
                  </form>
                </div>
              </div>
            </>
          )}

          {/* ── Search mode ── */}
          {mode === 'search' && activeSession && (
            <div>
              <div style={{ position: 'relative', marginBottom: '24px' }}>
                <input
                  ref={searchRef}
                  type="text"
                  value={searchQuery}
                  onChange={e => handleSearch(e.target.value)}
                  placeholder="Semantic search across all nodes..."
                  style={{ width: '100%', background: 'rgba(6,182,212,.04)', border: '1px solid rgba(6,182,212,.2)', borderRadius: '16px', padding: '16px 50px 16px 20px', color: '#e2e8f0', fontSize: '14px', fontFamily: "'JetBrains Mono',monospace", transition: 'border-color .2s', outline: 'none' }}
                  onFocus={e => (e.target.style.borderColor = 'rgba(6,182,212,.5)')}
                  onBlur={e => (e.target.style.borderColor = 'rgba(6,182,212,.2)')}
                />
                <div style={{ position: 'absolute', right: '18px', top: '50%', transform: 'translateY(-50%)', color: searching ? '#06b6d4' : 'rgba(148,163,184,.2)', fontSize: '18px', transition: 'all .2s', animation: searching ? 'spin 1s linear infinite' : 'none' }}>⌖</div>
              </div>
              {searchQuery.length >= 2 && !searching && searchResults.length === 0 && (
                <p style={{ color: 'rgba(148,163,184,.2)', fontSize: '11px', letterSpacing: '.2em', textTransform: 'uppercase', textAlign: 'center', padding: '40px 0' }}>No semantic matches found</p>
              )}
              {!searching && searchQuery.length < 2 && (
                <p style={{ color: 'rgba(148,163,184,.12)', fontSize: '11px', letterSpacing: '.2em', textTransform: 'uppercase', textAlign: 'center', padding: '60px 0' }}>Type to search using semantic similarity</p>
              )}
              {searchResults.length > 0 && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '12px', animation: 'fadeIn .3s ease' }}>
                  <p style={{ color: 'rgba(148,163,184,.25)', fontSize: '9px', letterSpacing: '.2em', textTransform: 'uppercase' }}>{searchResults.length} semantic matches</p>
                  {searchResults.map(node => (
                    <NodeCard
                      key={node.id}
                      node={node}
                      onBranch={n => { setSelectedParent(n); setMode('list'); setTimeout(() => inputRef.current?.focus(), 100); }}
                      onSynthesize={n => setSynthesisNode(n)}
                      onExpand={n => setExpandNode(n)}
                      onDelete={handleDeleteNode}
                      selectedId={null}
                      isNew={false}
                      isSearchResult
                      collapsedIds={collapsedIds}
                      toggleCollapse={toggleCollapse}
                    />
                  ))}
                </div>
              )}
            </div>
          )}

          {/* ── Firehose mode ── */}
          {mode === 'firehose' && (
            <FirehosePanel
              sessions={sessions}
              onWorkspaceUpdated={sessionId => { if (activeSession?.id === sessionId) fetchNodes(sessionId); }}
            />
          )}
        </div>
      )}
    </div>
  </>);
}