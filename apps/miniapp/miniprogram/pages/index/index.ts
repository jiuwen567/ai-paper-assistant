import { API_BASE_URL } from "../../config/api";

Component({
  data: {
    loading: false,
    status: "尚未连接",
    detail: "点击检查，确认小程序可以请求 Django API。",
    apiBaseUrl: API_BASE_URL,
  },
  methods: {
    checkConnection() {
      if (this.data.loading) return;
      this.setData({
        loading: true,
        status: "检查中",
        detail: "正在请求 API…",
      });
      wx.request<{ status?: string; service?: string }>({
        url: `${API_BASE_URL}/api/v1/health/live/`,
        method: "GET",
        timeout: 10000,
        success: (response) => {
          if (
            response.statusCode === 200 &&
            response.data?.status === "ok" &&
            response.data?.service === "api"
          ) {
            this.setData({
              status: "API 已连接",
              detail: "API 存活检查通过；依赖服务状态请在 Web 环境概览查看。",
            });
          } else {
            this.setData({
              status: "API 返回异常",
              detail: `HTTP ${response.statusCode}，请检查后端服务。`,
            });
          }
        },
        fail: () =>
          this.setData({
            status: "连接失败",
            detail:
              "请确认 API 已启动、地址可达，并检查开发工具的合法域名校验设置。",
          }),
        complete: () => this.setData({ loading: false }),
      });
    },
  },
});
