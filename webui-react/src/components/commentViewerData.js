export const COMMENT_LEVEL_OPTIONS = [
  { value: '', label: '全部层级' },
  { value: '1', label: '一级评论' },
  { value: '2', label: '二级回复' },
];

export const SORT_OPTIONS = [
  { value: 'published_at_desc', label: '时间倒序' },
  { value: 'published_at_asc', label: '时间正序' },
];

export function formatDateTime(value) {
  if (!value) return '-';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString();
}

export function formatSourceTitle(source) {
  if (!source) return '';
  return source.content_title || `作品 ${source.platform_content_id}`;
}
