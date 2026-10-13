import React, { useId } from "react";
import { Shuffle, PencilSimple, Sparkle } from "@phosphor-icons/react";

export function MartialSoulPicker({ config, value, onChange }) {
  const id = useId();
  const modes = [
    { id: "recommended", label: "推荐武魂", Icon: Sparkle },
    ...(config.allow_custom
      ? [{ id: "custom", label: "自己填写", Icon: PencilSimple }]
      : []),
    ...(config.allow_random
      ? [{ id: "random", label: "随机觉醒", Icon: Shuffle }]
      : []),
  ];
  return (
    <fieldset className="soul-picker">
      <legend>你想觉醒什么武魂？</legend>
      <p className="soul-note">先决定武魂，第一次开场就完成觉醒与魂力测定。</p>
      <div className="soul-modes">
        {modes.map(({ id: mode, label, Icon }) => (
          <label className={value.mode === mode ? "selected" : ""} key={mode}>
            <input
              type="radio"
              name={`${id}-mode`}
              checked={value.mode === mode}
              onChange={() =>
                onChange({
                  mode,
                  name: mode === "recommended" ? config.choices[0].name : "",
                })
              }
            />
            <Icon size={17} aria-hidden="true" />
            <span>{label}</span>
          </label>
        ))}
      </div>
      {value.mode === "recommended" && (
        <div className="soul-choices">
          {config.choices.map((choice) => (
            <label
              className={value.name === choice.name ? "selected" : ""}
              key={choice.name}
            >
              <input
                type="radio"
                name={`${id}-soul`}
                checked={value.name === choice.name}
                onChange={() =>
                  onChange({ mode: "recommended", name: choice.name })
                }
              />
              <span>
                <strong>{choice.name}</strong>
                <small>{choice.description}</small>
              </span>
            </label>
          ))}
        </div>
      )}
      {value.mode === "custom" && (
        <div className="soul-custom">
          <label className="field-label" htmlFor={`${id}-name`}>
            武魂名称
          </label>
          <input
            id={`${id}-name`}
            value={value.name}
            onChange={(e) => onChange({ mode: "custom", name: e.target.value })}
            maxLength={40}
            required
            autoComplete="off"
            placeholder="写下你想觉醒的武魂"
          />
          <small>
            选择武魂类型；初始魂力由故事规则决定，魂环与能力在后续成长中获得。
          </small>
        </div>
      )}
      {value.mode === "random" && (
        <p className="soul-random-note">
          把这份惊喜留到觉醒时揭晓。随机结果只抽一次，重试不会重抽。
        </p>
      )}
      <p className="fine-print">
        武魂选择与创建角色免费，生成故事时才消耗积分。
      </p>
    </fieldset>
  );
}
