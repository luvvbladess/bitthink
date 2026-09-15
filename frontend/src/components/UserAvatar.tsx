import { Avatar } from '@mui/material';
import type { SxProps, Theme } from '@mui/material/styles';

type UserLike = {
  first_name?: string;
  email?: string;
  avatar_url?: string | null;
};

type Props = {
  user?: UserLike | null;
  sx?: SxProps<Theme>;
};

export function UserAvatar({ user, sx }: Props) {
  const initial = (user?.first_name || user?.email || '?')[0]?.toUpperCase();
  const src = user?.avatar_url || undefined;
  return (
    <Avatar
      key={src || 'none'}
      src={src}
      imgProps={{ alt: '' }}
      sx={{
        borderRadius: '8px',
        bgcolor: 'var(--bt-glow-strong)',
        color: 'primary.light',
        fontWeight: 650,
        ...sx,
      }}
    >
      {initial}
    </Avatar>
  );
}
