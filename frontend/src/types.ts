export type Coordinates = [longitude: number, latitude: number];
export type CameraStatus = 'online' | 'offline' | 'unknown';
export type PlaybackType = 'hls' | 'iframe' | 'rtsp';

export type MapPoint = {
  id: number; slug: string; name: string; city: string; category: string;
  coordinates: Coordinates; camera_count: number; online_count: number; status: 'online' | 'offline';
};
export type MapCluster = {
  id: string; coordinates: Coordinates; place_count: number; camera_count: number;
  online_count: number; status: 'online' | 'offline';
};
export type MapResponse = {
  mode: 'points' | 'clusters'; points: MapPoint[]; clusters: MapCluster[]; truncated: boolean;
};
export type SearchSuggestion = {
  kind: 'city' | 'address' | 'place'; label: string; coordinates: Coordinates; place_id: number | null;
};
export type SearchResponse = { suggestions: SearchSuggestion[] };

export type PublicCamera = {
  id: number; name: string; playback_type: PlaybackType; status: CameraStatus;
  last_checked_at: string | null; last_success_at: string | null;
  availability_note: string | null; source_name: string; source_page_url: string;
  attribution: string; playback_url: string | null; embed_host: string | null;
};
export type PlaceDetail = {
  id: number; slug: string; name: string; address: string | null; city: string;
  region: string; category: string; coordinates: Coordinates; cameras: PublicCamera[];
};

export type AdminRole = 'admin' | 'editor';
export type LoginResponse = { access_token: string; token_type: 'bearer'; expires_at: string; role: AdminRole };
export type AdminUser = { id: number; username: string; role: AdminRole };
export type AdminPlace = Omit<PlaceDetail, 'cameras'> & {
  is_published: boolean; created_at: string; updated_at: string;
};
export type PlaceInput = Omit<AdminPlace, 'id' | 'is_published' | 'created_at' | 'updated_at'>;
export type AdminSource = {
  id: number; owner_name: string; public_page_url: string; stream_url: string | null;
  secret_ref: string | null; attribution: string; permission_note: string;
  permission_evidence_url: string | null; permission_reviewed_at: string | null;
  embed_host: string | null; permission_expires_at: string | null;
  removal_contact: string | null; is_approved: boolean; created_at: string; updated_at: string;
};
export type SourceInput = Omit<AdminSource, 'id' | 'is_approved' | 'created_at' | 'updated_at'>;
export type AdminCamera = {
  id: number; place_id: number; source_id: number; name: string;
  playback_type: PlaybackType; valid_until: string | null; is_published: boolean;
  status: CameraStatus; last_checked_at: string | null; last_success_at: string | null;
  next_check_at: string | null; last_error_code: string | null;
  consecutive_failures: number; embed_verified_at: string | null;
  unpublished_reason: string | null; created_at: string; updated_at: string;
};
export type CameraCheck = {
  id: number; camera_id: number; checked_at: string;
  result: CameraStatus; code: string; duration_ms: number;
};
export type CameraInput = Pick<AdminCamera, 'place_id' | 'source_id' | 'name' | 'playback_type' | 'valid_until'>;
export type AuditEvent = {
  id: number; actor_id: number | null; action: string; entity_type: string;
  entity_id: number | null; summary: string; created_at: string;
};
export type ImportInput = { format: 'csv' | 'geojson'; content: string };
export type ImportPreview = {
  items: { row: number; slug: string; action: 'create' | 'update'; has_camera: boolean }[];
  errors: { row: number; message: string }[];
};
export type ImportResult = { created: number; updated: number; draft_cameras: number };
