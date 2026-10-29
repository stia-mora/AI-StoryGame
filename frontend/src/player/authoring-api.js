export async function authoringRequest(path, body, options = {}) {
  let response;
  try {
    response = await fetch(path, {
      credentials: "include",
      ...(body === undefined ? {} : {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
      }),
      ...options,
    });
  } catch {
    throw new Error("连接中断，请检查网络后重试。已接受的导入任务仍会在后台继续。");
  }
  let value;
  try { value = await response.json(); }
  catch { throw new Error("服务暂时没有返回有效结果，请稍后重试。"); }
  if (!response.ok) {
    const detail = value.detail || value.error;
    throw new Error(response.status === 401 ? "登录已过期，请重新登录后继续。"
      : typeof detail === "string" ? detail : "操作未完成，请稍后重试。");
  }
  return value;
}

export const authoringAction = (name, data) => authoringRequest(`/api/authoring/action/${name}`, data);
export const authoringStatus = value => ({
  pending: "排队中", running: "执行中", succeeded: "已完成", failed: "未完成",
  pending_review: "待审批", published: "已上架", rejected: "已拒绝",
}[value] || value);
