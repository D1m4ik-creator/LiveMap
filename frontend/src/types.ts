export type PublicCamera = {
  id: number;
  name: string;
  playback_type: 'hls' | 'iframe' | 'rtsp';
  status: 'online' | 'offline' | 'unknown';
  last_checked_at: string | null;
  last_success_at: string | null;
  availability_note: string | null;
  source_name: string;
  source_page_url: string;
  attribution: string;
  playback_url: string | null;
  embed_host: string | null;
};

export type PlaceDetail = {
  id: number;
  name: string;
  city: string;
  address: string | null;
  cameras: PublicCamera[];
};
