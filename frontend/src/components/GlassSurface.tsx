import { Box, styled } from '@mui/material';

export const GlassSurface = styled(Box)(({ theme }) => ({
  position: 'relative',
  borderRadius: theme.shape.borderRadius,
  background: theme.palette.background.paper,
  border: `1px solid ${theme.palette.divider}`,
  overflow: 'hidden',
}));

export const InnerCore = styled(Box)(({ theme }) => ({
  borderRadius: theme.shape.borderRadius,
  background: theme.palette.surface.elevated,
}));
