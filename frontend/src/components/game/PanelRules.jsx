/* 5E 兼容规则面板(规则 tab)—— 纯机械从 game-panels.jsx 搬出,零行为变化。 */
import React from 'react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';

// ── 5E-compatible 规则面板 ─────────────────────────────────────
// 内部 ruleset id "dnd5e"，对外文案统一使用 "5E compatible / 五版规则兼容"。
// 不引入任何官方 Dungeons & Dragons 商标或非 SRD IP。
function PanelRules({ state }) {
  const { t } = useTranslation();
  const ruleset = (state && state.ruleset) || {};
  const pc = (state && state.player_character) || {};
  const scene = (state && state.scene) || {};
  const encounter = (state && state.encounter) || {};
  const diceLog = Array.isArray(state && state.dice_log) ? state.dice_log : [];
  const contentPack = (state && state.content_pack) || {};
  const [busy, setBusy] = useState(false);
  const [errorMsg, setErrorMsg] = useState("");

  async function runRules(fnName, ...args) {
    if (!window.api?.rules) { setErrorMsg(t('game.rules.api_not_registered')); return null; }
    setBusy(true);
    setErrorMsg("");
    try {
      const data = await window.api.rules[fnName](...args);
      if (!data || !data.ok) throw new Error(data?.error || data?.detail || t('game.panels.rules_request_failed', { fn: fnName }));
      window.dispatchEvent(new CustomEvent("game-state-refresh"));
      return data;
    } catch (e) {
      setErrorMsg(String(e?.message || e));
      return null;
    } finally {
      setBusy(false);
    }
  }

  async function move(toId) { await runRules("move", toId); }
  async function doAction(body) { await runRules("action", body); }
  async function startEncounter(encId) { await runRules("encounterStart", encId); }
  async function nextTurn() { await runRules("encounterNext"); }

  const moduleLoaded = !!scene.module_id;
  const currentRoom = scene.current_room || {};
  const hpPct = pc.max_hp > 0 ? Math.max(0, Math.min(100, Math.round(100 * (pc.hp || 0) / pc.max_hp))) : 0;
  const turnToken = `${encounter.encounter_id}:${encounter.round}:${encounter.turn_index}`;
  const playerTurn = (encounter.initiative_order || [])[encounter.turn_index]?.id === 'player'
    && encounter.action_used !== turnToken && pc.hp > 0;

  // 非 module_adventure 剧本（小说 / freeform）显式说明此 tab 不适用，
  // 避免在小说存档里误显示一套不属于该剧本的 5E 默认角色卡 + 模组按钮。
  // 加载模组的入口只在 Platform『冒险模组』页（那里会建新存档，不污染当前剧本）。
  const packKind = contentPack.kind || "freeform";
  if (packKind !== "module_adventure") {
    const packTitle = packKind === "novel_adaptation" ? t('game.rules.novel_pack') : t('game.rules.freeform_pack');
    return (
      <div className="gp-stack">
        <div className="gp-section">
          <div className="section-head">
            <h3>{t('game.rules.not_applicable')}</h3>
            <span className="pill"><span className="dot" /> {packTitle}</span>
          </div>
          <p className="gp-bio" style={{margin: "8px 0 0"}}>
            {t('game.rules.not_applicable_desc', { pack: packTitle })}
          </p>
          <p className="muted-2" style={{fontSize: 12.5, marginTop: 10}}>
            {t('game.rules.try_module_hint')}
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="gp-stack">
      {/* 模组元信息 */}
      <div className="gp-section">
        <div className="section-head">
          <h3>{t('game.rules.module_info', { label: ruleset.public_label || "5E compatible / 五版规则兼容" })}</h3>
          <span className="pill ok"><span className="dot ok" /> {t('game.rules.loaded')}</span>
        </div>
        <div className="gp-kv">
          <div className="gp-row"><span className="gp-label">{t('game.rules.module_label')}</span><strong>{(scene.module_manifest||{}).name_cn || (scene.module_manifest||{}).name || scene.module_id}</strong></div>
          <div className="gp-row"><span className="gp-label">tagline</span><span style={{fontStyle:"italic",opacity:0.85}}>{(scene.module_manifest||{}).tagline || "—"}</span></div>
        </div>
        {errorMsg ? <p className="muted-2" style={{color:"var(--danger)",marginTop:6}}>{errorMsg}</p> : null}
      </div>

      {/* 角色卡 */}
      <div className="gp-section">
        <div className="section-head"><h3>{t('game.rules.character_card')}</h3>{pc.level ? <span className="pill"><span className="dot" /> Lv {pc.level}</span> : null}</div>
        <div className="gp-kv">
          <div className="gp-row"><span className="gp-label">{t('game.status.name')}</span><strong>{pc.name || "—"}</strong></div>
          <div className="gp-row"><span className="gp-label">{t('game.rules.class')}</span><span>{pc.class_name || "—"}</span></div>
          <div className="gp-row"><span className="gp-label">{t('game.rules.species')}</span><span>{pc.species || "—"}</span></div>
          <div className="gp-row"><span className="gp-label">{t('game.status.hp')}</span><span>{pc.hp || 0} / {pc.max_hp || 0}
            <span style={{display:"inline-block",width:80,height:6,background:"var(--panel-3)",borderRadius:3,marginLeft:8,verticalAlign:"middle"}}>
              <span style={{display:"block",height:"100%",width:`${hpPct}%`,background:hpPct>50?"var(--green)":hpPct>25?"var(--accent)":"var(--danger)",borderRadius:3}} />
            </span>
          </span></div>
          <div className="gp-row"><span className="gp-label">{t('game.status.ac')}</span><span>{pc.ac || "—"}</span></div>
          <div className="gp-row"><span className="gp-label">{t('game.rules.proficiency_bonus')}</span><span>+{pc.proficiency_bonus || 0}</span></div>
        </div>
        {pc.abilities && Object.keys(pc.abilities).length > 0 ? (
          <div style={{display:"grid",gridTemplateColumns:"repeat(6,1fr)",gap:4,marginTop:6,fontSize:12}}>
            {["str","dex","con","int","wis","cha"].map(a => {
              const score = pc.abilities[a];
              if (score == null) return null;
              const mod = Math.floor((score - 10) / 2);
              return (
                <div key={a} style={{textAlign:"center",padding:"4px 0",background:"var(--panel-3)",borderRadius:4}}>
                  <div className="muted-2" style={{fontSize:10,textTransform:"uppercase"}}>{a}</div>
                  <strong>{score}</strong>
                  <div className="muted-2" style={{fontSize:10}}>{mod >= 0 ? "+" : ""}{mod}</div>
                </div>
              );
            })}
          </div>
        ) : null}
        {Array.isArray(pc.conditions) && pc.conditions.length ? (
          <div style={{marginTop:6}}>
            <span className="muted-2" style={{fontSize:11,marginRight:6}}>{t('game.rules.condition_label')}</span>
            {pc.conditions.map((c,i) => <span key={i} className="pill" style={{marginRight:4}}>{c}</span>)}
          </div>
        ) : null}
      </div>

      {/* 当前房间 */}
      {moduleLoaded ? (
        <div className="gp-section">
          <div className="section-head"><h3>{t('game.rules.current_room')}</h3><span className="muted-2 mono" style={{fontSize:11}}>{scene.location_id}</span></div>
          <div className="gp-kv">
            <div className="gp-row"><span className="gp-label">{t('game.rules.room_name')}</span><strong>{currentRoom.name || "—"}</strong></div>
          </div>
          <p className="gp-bio" style={{whiteSpace:"pre-wrap"}}>{currentRoom.description || ""}</p>
          {Array.isArray(currentRoom.visible_clues) && currentRoom.visible_clues.length ? (
            <div style={{marginTop:6}}>
              <div className="muted-2" style={{fontSize:11,marginBottom:3}}>{t('game.rules.visible_clues_label')}</div>
              <ul style={{margin:0,paddingLeft:16}}>
                {currentRoom.visible_clues.map((c,i) => <li key={i} style={{fontSize:12}}>{c.text || c}</li>)}
              </ul>
            </div>
          ) : null}
          {Object.values(scene.unlocked_facts || {}).length > 0 && (
            <div style={{marginTop:8}}>
              <div className="muted-2" style={{fontSize:11}}>{t('game.rules.unlocked_clues')}</div>
              <ul style={{margin:0,paddingLeft:16}}>{Object.entries(scene.unlocked_facts).map(([id, fact]) => (
                <li key={id} style={{fontSize:12}}>{fact}</li>
              ))}</ul>
            </div>
          )}
          {Array.isArray(currentRoom.exits) && currentRoom.exits.length ? (
            <div style={{marginTop:6}}>
              <div className="muted-2" style={{fontSize:11,marginBottom:3}}>{t('game.rules.exits_label')}</div>
              <div style={{display:"flex",gap:4,flexWrap:"wrap"}}>
                {currentRoom.exits.map((e,i) => (
                  <button key={i} disabled={busy} onClick={() => move(e.to)} style={{fontSize:12}}>
                    {e.label || e.to}
                  </button>
                ))}
              </div>
            </div>
          ) : null}
          {Array.isArray(currentRoom.checks) && currentRoom.checks.length ? (
            <div style={{marginTop:8}}>
              <div className="muted-2" style={{fontSize:11,marginBottom:3}}>{t('game.rules.checks_label')}</div>
              <div style={{display:"flex",gap:4,flexWrap:"wrap"}}>
                {currentRoom.checks.map((c,i) => (
                  <button key={i} disabled={busy} onClick={() => doAction({
                    kind: c.kind || "skill_check",
                    check_id: c.id || `check_${i}`,
                  })} style={{fontSize:12}}>
                    {c.kind === "saving_throw" ? t('game.rules.saving_throw', { ability: (c.ability||"").toUpperCase(), dc: c.dc }) : t('game.rules.skill_check', { skill: c.skill, dc: c.dc })}
                  </button>
                ))}
              </div>
            </div>
          ) : null}
          {(currentRoom.flags || {}).can_short_rest ? (
            <div style={{marginTop:6}}>
              <button disabled={busy} onClick={() => doAction({kind:"short_rest"})}>{t('game.rules.short_rest')}</button>
            </div>
          ) : null}
          {Array.isArray(currentRoom.enemies) && currentRoom.enemies.some(e => scene.entity_outcomes?.[e.id] !== 'defeated') && !encounter.active ? (
            <div style={{marginTop:8}}>
              <div className="muted-2" style={{fontSize:11,marginBottom:3}}>{t('game.rules.encounter_label')}</div>
              <button disabled={busy || pc.hp <= 0} className="primary" onClick={() => startEncounter(`${scene.location_id}_combat`)} style={{fontSize:12}}>
                {t('game.rules.start_combat')}
              </button>
            </div>
          ) : null}
        </div>
      ) : null}

      {/* 战斗面板 */}
      {encounter.active ? (
        <div className="gp-section">
          <div className="section-head">
            <h3>{t('game.rules.combat_title', { round: encounter.round })}</h3>
            <span className="pill ok"><span className="dot ok" /> {t('game.rules.round_info', { current: encounter.turn_index + 1, total: (encounter.initiative_order||[]).length })}</span>
          </div>
          <div style={{marginTop:6}}>
            <div className="muted-2" style={{fontSize:11,marginBottom:3}}>{t('game.rules.initiative_order')}</div>
            <ol style={{margin:0,paddingLeft:18}}>
              {(encounter.initiative_order||[]).map((o,i) => {
                const isCurrent = i === encounter.turn_index;
                const comb = (encounter.combatants||[]).find(c => c.id === o.id) || {};
                return (
                  <li key={i} style={{fontSize:12,fontWeight:isCurrent?700:400,opacity:comb.defeated?0.5:1}}>
                    {o.name} <span className="muted-2">({o.init}, {comb.side})</span> · HP {comb.hp}/{comb.max_hp}
                    {comb.defeated ? t('game.rules.defeated') : ""}
                  </li>
                );
              })}
            </ol>
          </div>
          <div style={{display:"flex",gap:4,flexWrap:"wrap",marginTop:8}}>
            {(encounter.combatants||[]).filter(c => c.side === "enemy" && !c.defeated).map(e => (
              <button key={e.id} disabled={busy || !playerTurn} className="primary" onClick={() => doAction({kind:"attack", target: e.id, turn_token: turnToken})} style={{fontSize:12}}>
                {t('game.rules.attack', { name: e.name })}
              </button>
            ))}
            <button disabled={busy} onClick={nextTurn} style={{fontSize:12}}>{t(playerTurn ? 'game.rules.end_my_action' : 'game.rules.continue_combat')}</button>
          </div>
          <p className="muted-2" style={{fontSize:12}}>{t('game.rules.automatic_enemy_turns')}</p>
        </div>
      ) : null}

      {/* 骰子日志 */}
      <div className="gp-section">
        <div className="section-head"><h3>{t('game.rules.dice_log')}</h3><span className="muted-2 mono" style={{fontSize:11}}>{t('game.rules.dice_count', { count: diceLog.length })}</span></div>
        {diceLog.length === 0 ? (
          <p className="muted-2" style={{fontSize:12}}>{t('game.rules.dice_empty')}</p>
        ) : (
          <ul style={{margin:0,paddingLeft:0,listStyle:"none",maxHeight:240,overflowY:"auto"}}>
            {diceLog.slice().reverse().map((d,i) => (
              <li key={d.id || i} style={{padding:"4px 6px",borderBottom:"1px solid var(--line-soft)",fontSize:12}}>
                <div>
                  <strong>{d.kind}</strong>
                  {d.actor ? <span className="muted-2"> · {d.actor}</span> : null}
                  {d.target ? <span className="muted-2"> → {d.target}</span> : null}
                  {d.success === true ? <span className="pill ok" style={{marginLeft:6}}>{t('game.rules.success')}</span>
                    : d.success === false ? <span className="pill" style={{marginLeft:6,background:"var(--danger)",color:"#fff"}}>{t('game.rules.fail')}</span>
                    : null}
                </div>
                <div className="muted-2" style={{fontSize:11}}>
                  {d.expression || ""} = [{(d.rolls||[]).join(",")}]{typeof d.modifier === "number" && d.modifier ? ` ${d.modifier>=0?"+":""}${d.modifier}` : ""}
                  {typeof d.total === "number" ? ` → ${d.total}` : ""}
                  {typeof d.dc === "number" ? ` vs DC ${d.dc}` : ""}
                  {d.damage ? ` · ${t('game.status.damage')} ${d.damage.total}` : ""}
                  {d.reason ? ` · ${d.reason}` : ""}
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

export { PanelRules };
