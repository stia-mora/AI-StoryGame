import React, { useEffect, useState } from "react";
import { ArrowLeft } from "@phosphor-icons/react";
import { Button, Loading, Notice, points } from "./shared.jsx";

const starter = [
  {
    id: "traveller",
    name: "初来乍到的旅人",
    role: "旅人",
    description: "从一个新的身份开始，认识这个世界。",
    background: "",
  },
];
export function Manage({ navigate }) {
  const [data, setData] = useState(null),
    [error, setError] = useState(""),
    [message, setMessage] = useState(""),
    [busy, setBusy] = useState(false),
    [tab, setTab] = useState("stories");
  const [model, setModel] = useState({
    name: "玩家服务模型",
    api_id: "",
    model: "",
    max_output: 6144,
    enabled: true,
    tools_mode: "internal",
  });
  const [story, setStory] = useState({
    script_id: "",
    profile_id: "",
    title: "",
    introduction: "",
    cover: "",
    identities: JSON.stringify(starter, null, 2),
    defaults: "{}",
    status: "unlisted",
    sort_order: 0,
  });
  const [grant, setGrant] = useState({ user_id: "", points: 100, reason: "" }),
    [coupon, setCoupon] = useState({
      label: "积分兑换",
      points: 100,
      max_uses: 1,
      expires_at: "",
    });
  const [rate, setRate] = useState({
    input_per_1000: 1,
    output_per_1000: 4,
    daily_points: 100,
  });
  const load = async () => {
    try {
      const d = await window.api.player.manage();
      setData(d);
      setRate({
        input_per_1000: d.rates.input_micro_per_token / 1000,
        output_per_1000: d.rates.output_micro_per_token / 1000,
        daily_points: d.rates.daily_micro / 1e6,
      });
    } catch (e) {
      setError(e.message);
    }
  };
  useEffect(() => {
    load();
  }, []);
  const submit = async (resource, body) => {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const r = await window.api.player.configure(resource, body);
      setMessage(r.code ? `兑换码（仅展示这一次）：${r.code}` : "已保存。");
      await load();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };
  const input = (state, set, key, label, type = "text") => (
    <label className="field-label">
      {label}
      <input
        type={type}
        step={
          type === "number" &&
          !["user_id", "max_uses", "max_output", "sort_order"].includes(key)
            ? "any"
            : undefined
        }
        value={state[key]}
        onChange={(e) => set({ ...state, [key]: e.target.value })}
        required={key !== "expires_at"}
      />
    </label>
  );
  if (!data)
    return error ? (
      <main className="player-shell">
        <Notice error>{error}</Notice>
        <Button onClick={load}>重试</Button>
      </main>
    ) : (
      <Loading />
    );
  const models = (data.models.apis || [])
    .flatMap((a) =>
      (a.models || [])
        .filter((m) => m.enabled !== false)
        .map((m) => ({
          api: a.id || a.api_id,
          model: m.real_name || m.id,
          label: `${a.name || a.id} / ${m.real_name || m.id}`,
        })),
    )
    .filter(
      (m) =>
        data.credentials.some((c) => c.api_id === m.api) ||
        m.api === "vertex_ai",
    );
  return (
    <main id="player-main" className="player-shell management">
      <button className="back-link" onClick={() => navigate("/play")}>
        <ArrowLeft size={18} /> 玩家入口
      </button>
      <h1>玩家服务管理</h1>
      <nav className="management-tabs" aria-label="服务管理分类">
        {[
          ["stories", "剧本目录"],
          ["models", "服务模型"],
          ["credits", "积分与兑换码"],
          ["accounts", "账户权限"],
          ["bills", "账单"],
        ].map(([id, label]) => (
          <button
            key={id}
            aria-current={tab === id ? "page" : undefined}
            onClick={() => setTab(id)}
          >
            {label}
          </button>
        ))}
      </nav>
      {error && <Notice error>{error}</Notice>}
      {message && <Notice>{message}</Notice>}
      {tab === "stories" && (
        <>
          <section className="management-list">
            {data.stories.map((s) => (
              <button
                key={s.id}
                onClick={() =>
                  setStory({
                    ...s,
                    identities: JSON.stringify(s.identities, null, 2),
                    defaults: JSON.stringify(s.defaults, null, 2),
                  })
                }
              >
                <strong>{s.title}</strong>
                <span>
                  {
                    {
                      published: "已上架",
                      unlisted: "已下架",
                      suspended: "紧急停用",
                    }[s.status]
                  }
                </span>
              </button>
            ))}
          </section>
          <form
            className="manage-form"
            onSubmit={(e) => {
              e.preventDefault();
              try {
                submit("stories", {
                  ...story,
                  script_id: Number(story.script_id),
                  profile_id: Number(story.profile_id),
                  identities: JSON.parse(story.identities),
                  defaults: JSON.parse(story.defaults),
                });
              } catch {
                setError("身份或开局配置不是有效 JSON");
              }
            }}
          >
            <h2>上架设置</h2>
            <label className="field-label">
              已有剧本
              <select
                value={story.script_id}
                onChange={(e) =>
                  setStory({
                    ...story,
                    script_id: e.target.value,
                    title:
                      data.scripts.find((s) => String(s.id) === e.target.value)
                        ?.title || "",
                  })
                }
                required
              >
                <option value="">选择剧本</option>
                {data.scripts.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.title} · {s.review_status}
                  </option>
                ))}
              </select>
            </label>
            <label className="field-label">
              服务模型
              <select
                value={story.profile_id}
                onChange={(e) =>
                  setStory({ ...story, profile_id: e.target.value })
                }
                required
              >
                <option value="">选择服务模型</option>
                {data.profiles.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
            </label>
            {input(story, setStory, "title", "玩家看到的标题")}
            <label className="field-label">
              简短介绍
              <textarea
                rows={3}
                value={story.introduction}
                onChange={(e) =>
                  setStory({ ...story, introduction: e.target.value })
                }
              />
            </label>
            <label className="field-label">
              封面地址（可选）
              <input
                value={story.cover}
                onChange={(e) => setStory({ ...story, cover: e.target.value })}
                placeholder="HTTPS 图片或 /assets/ 路径"
              />
            </label>
            <label className="field-label">
              推荐身份
              <textarea
                rows={8}
                value={story.identities}
                onChange={(e) =>
                  setStory({ ...story, identities: e.target.value })
                }
              />
            </label>
            <details>
              <summary>默认开局配置</summary>
              <p className="fine-print">
                可配置
                birthpoint、story_intent、player_origin、identity_known；玩家无法修改这些配置。
              </p>
              <textarea
                aria-label="默认开局配置"
                rows={7}
                value={story.defaults}
                onChange={(e) =>
                  setStory({ ...story, defaults: e.target.value })
                }
              />
            </details>
            <label className="field-label">
              上架状态
              <select
                value={story.status}
                onChange={(e) => setStory({ ...story, status: e.target.value })}
              >
                <option value="unlisted">下架（已有存档可继续）</option>
                <option value="published">上架</option>
                <option value="suspended">紧急停用（停止生成）</option>
              </select>
            </label>
            {input(story, setStory, "sort_order", "排序", "number")}
            <Button disabled={busy}>保存目录配置</Button>
          </form>
        </>
      )}
      {tab === "models" && (
        <>
          <section className="management-list">
            {data.profiles.map((p) => (
              <button key={p.id} onClick={() => setModel(p)}>
                <strong>{p.name}</strong>
                <span>
                  {p.model} · {p.enabled ? "启用" : "停用"}
                </span>
              </button>
            ))}
          </section>
          <form
            className="manage-form"
            onSubmit={(e) => {
              e.preventDefault();
              submit("profiles", model);
            }}
          >
            <h2>平台提供的文本模型</h2>
            {input(model, setModel, "name", "名称")}
            <label className="field-label">
              已有凭据与模型
              <select
                value={`${model.api_id}|${model.model}`}
                onChange={(e) => {
                  const [api_id, chosen] = e.target.value.split("|");
                  setModel({ ...model, api_id, model: chosen });
                }}
                required
              >
                <option value="|">选择文本模型</option>
                {models.map((m) => (
                  <option
                    key={`${m.api}|${m.model}`}
                    value={`${m.api}|${m.model}`}
                  >
                    {m.label}
                  </option>
                ))}
              </select>
            </label>
            {input(
              model,
              setModel,
              "max_output",
              "每次输出预算 Token",
              "number",
            )}
            <label className="field-label">
              工具权限
              <select
                value={model.tools_mode || "internal"}
                onChange={(e) =>
                  setModel({ ...model, tools_mode: e.target.value })
                }
              >
                <option value="internal">内部游玩工具</option>
                <option value="none">仅叙事（适用于拒绝工具参数的接口）</option>
              </select>
            </label>
            <label>
              <input
                type="checkbox"
                checked={model.enabled}
                onChange={(e) =>
                  setModel({ ...model, enabled: e.target.checked })
                }
              />{" "}
              启用
            </label>
            <p className="fine-print">
              使用当前管理员已有凭据，玩家不需要 API
              设置。后台制作与记忆维护由平台承担。
            </p>
            <Button disabled={busy}>保存服务模型</Button>
            <Button
              quiet
              type="button"
              onClick={() =>
                setModel({
                  name: "玩家服务模型",
                  api_id: "",
                  model: "",
                  max_output: 6144,
                  enabled: true,
                  tools_mode: "internal",
                })
              }
            >
              新增模型配置
            </Button>
          </form>
        </>
      )}
      {tab === "credits" && (
        <div className="manage-grid">
          <form
            className="manage-form"
            onSubmit={(e) => {
              e.preventDefault();
              submit("rates", rate);
            }}
          >
            <h2>积分费率</h2>
            {input(
              rate,
              setRate,
              "input_per_1000",
              "每千输入 Token 积分",
              "number",
            )}
            {input(
              rate,
              setRate,
              "output_per_1000",
              "每千输出 Token 积分",
              "number",
            )}
            {input(rate, setRate, "daily_points", "每日免费积分", "number")}
            <p className="fine-print">
              改价仅影响之后的回合，已预留回合保留原费率。
            </p>
            <Button disabled={busy}>更新费率</Button>
          </form>
          <form
            className="manage-form"
            onSubmit={(e) => {
              e.preventDefault();
              submit("grants", grant);
            }}
          >
            <h2>发放长期积分</h2>
            {input(grant, setGrant, "user_id", "账户 ID", "number")}
            {input(grant, setGrant, "points", "积分", "number")}
            {input(grant, setGrant, "reason", "发放原因")}
            <Button disabled={busy}>发放并写入审计</Button>
          </form>
          <form
            className="manage-form"
            onSubmit={(e) => {
              e.preventDefault();
              submit("codes", {
                ...coupon,
                expires_at: coupon.expires_at
                  ? new Date(coupon.expires_at).toISOString()
                  : null,
              });
            }}
          >
            <h2>创建兑换码</h2>
            {input(coupon, setCoupon, "label", "备注")}
            {input(coupon, setCoupon, "points", "每人积分", "number")}
            {input(coupon, setCoupon, "max_uses", "最多兑换人数", "number")}
            {input(
              coupon,
              setCoupon,
              "expires_at",
              "到期时间（可选）",
              "datetime-local",
            )}
            <Button disabled={busy}>生成兑换码</Button>
          </form>
          <section className="manage-form">
            <h2>兑换码管理</h2>
            {data.codes.map((c) => (
              <div className="management-row" key={c.id}>
                <span>
                  {c.label} · {points(c.amount_micro)} 积分 · {c.used_count}/
                  {c.max_uses}
                </span>
                <Button
                  quiet
                  disabled={busy}
                  onClick={() =>
                    submit("codes", { id: c.id, enabled: !c.enabled })
                  }
                >
                  {c.enabled ? "停用" : "启用"}
                </Button>
              </div>
            ))}
          </section>
        </div>
      )}
      {tab === "accounts" && (
        <section className="management-list">
          {data.accounts.map((a) => (
            <div className="management-row" key={a.id}>
              <span>
                #{a.id} {a.display_name || a.username} · {a.role}
              </span>
              <select
                aria-label={`${a.username}的账户权限`}
                value={a.account_mode}
                disabled={a.role === "admin"}
                onChange={async (e) => {
                  try {
                    await window.api.player.accountMode(a.id, e.target.value);
                    await load();
                  } catch (error) {
                    setError(error.message);
                  }
                }}
              >
                <option value="player">仅游玩</option>
                <option value="creator">游玩与创作</option>
              </select>
            </div>
          ))}
        </section>
      )}
      {tab === "bills" && (
        <section className="bill-table">
          <table>
            <thead>
              <tr>
                <th>账户 / 存档</th>
                <th>状态</th>
                <th>实扣积分</th>
                <th>时间</th>
              </tr>
            </thead>
            <tbody>
              {data.bills.map((b) => (
                <tr key={b.id}>
                  <td>
                    #{b.user_id} / {b.save_id}
                  </td>
                  <td>
                    {b.status}
                    {b.reason && <small>{b.reason}</small>}
                  </td>
                  <td>{points(b.charged_micro)}</td>
                  <td>{new Date(b.created_at).toLocaleString("zh-CN")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
    </main>
  );
}
