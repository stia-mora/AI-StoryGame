import React, { useEffect, useRef } from "react";

export function PlayerHelp({ open, onClose }) {
  const dialog = useRef(null);
  useEffect(() => {
    const element = dialog.current;
    if (open && !element.open) element.showModal();
    if (!open && element.open) element.close();
  }, [open]);
  return (
    <dialog ref={dialog} className="player-help-dialog" aria-labelledby="player-help-title" onClose={onClose}>
      <div className="section-heading">
        <h2 id="player-help-title">游玩指引</h2>
        <button className="text-button" onClick={() => dialog.current.close()}>关闭</button>
      </div>
      <ol>
        <li><strong>选择故事与身份</strong><p>游客可以浏览已上架的故事。登录后选择身份、填写名字并创建角色；创建角色免费。</p></li>
        <li><strong>生成开场与行动</strong><p>先查看积分估算和本次费用上限，再开始生成。点击推荐行动会直接发送；也可以输入自己的行动或对话。快进会推进到下一处关键抉择。</p></li>
        <li><strong>积分与结算</strong><p>开场、行动和助手按实际模型用量计费，结算不超过本次报价上限。报价失败或余额不足时不会开始生成。积分页可查看余额和用量明细；阅读已保存内容免费。</p></li>
        <li><strong>保存与恢复</strong><p>以保存状态行和结算结果为准。停止可能保存并结算已生成的部分内容；未提交的预留会释放。断线后重新打开原存档，等待查询保存结果，避免重复发送。</p></li>
        <li><strong>状态、记录与助手</strong><p>状态中查看局势、角色、背包、人物、任务和世界线；记录中切换回合与存档。助手用于询问当前已知情况，与剧情生成互斥，提问前也会显示报价。</p></li>
      </ol>
      <p className="muted">历史阅读不会被新输出切走。请留意生成内容，重要决定由你判断。</p>
    </dialog>
  );
}
