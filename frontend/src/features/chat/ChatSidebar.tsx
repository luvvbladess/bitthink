import { useState } from 'react';
import {
  Box,
  IconButton,
  List,
  ListItemButton,
  Typography,
  TextField,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogContentText,
  DialogActions,
  Button,
} from '@mui/material';
import { Plus, Trash, PencilSimple, Check, X, MagnifyingGlass, ClockCounterClockwise } from '@phosphor-icons/react';
import { motion, AnimatePresence, useReducedMotion } from 'framer-motion';
import { BrandLink } from '@/components/BrandMark';
import { headerIconBtnSx } from '@/theme/effects';

export interface ConversationItem {
  id: string;
  title: string;
  message_count: number;
  is_active: boolean;
  shared?: boolean;
  role?: 'owner' | 'member';
}

interface Props {
  conversations: ConversationItem[];
  activeId?: string;
  onSelect: (id: string) => void;
  onCreate: () => void;
  onDelete: (id: string) => void;
  onRename: (id: string, title: string) => void;
  onClose?: () => void;
  generatingIds?: string[];
}

const SIDEBAR_W = { xs: '100%', md: 280 };

const actionBtnSx = {
  width: 28,
  height: 28,
  borderRadius: '8px',
  color: 'text.secondary',
  '&:hover': { color: 'text.primary', bgcolor: 'var(--bt-overlay)' },
} as const;

export function ChatSidebar({ conversations, activeId, onSelect, onCreate, onDelete, onRename, onClose, generatingIds = [] }: Props) {
  const reduce = useReducedMotion();
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState('');
  const [confirmDelete, setConfirmDelete] = useState<ConversationItem | null>(null);
  const [search, setSearch] = useState('');
  const filteredConversations = search.trim()
    ? conversations.filter((c) => c.title.toLowerCase().includes(search.trim().toLowerCase()))
    : conversations;

  const startEdit = (conv: ConversationItem) => {
    setEditingId(conv.id);
    setEditTitle(conv.title);
  };

  const saveEdit = () => {
    if (editingId && editTitle.trim()) {
      onRename(editingId, editTitle.trim());
    }
    setEditingId(null);
  };

  return (
    <Box
      sx={{
        height: '100%',
        display: 'flex',
        flexDirection: 'column',
        width: SIDEBAR_W,
        minWidth: { md: 280 },
        maxWidth: { md: 280 },
        overflow: 'hidden',
        bgcolor: 'var(--bt-sidebar)',
        backgroundImage: 'radial-gradient(ellipse 90% 40% at 0% 0%, var(--bt-glow), transparent 58%)',
        borderRight: onClose ? 'none' : '1px solid',
        borderColor: 'var(--bt-line)',
        boxShadow: onClose ? 'none' : 'inset -1px 0 0 var(--bt-overlay-faint)',
      }}
    >
      <Box
        sx={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          px: 1.75,
          minHeight: 56,
          flexShrink: 0,
        }}
      >
        <BrandLink variant="sidebar" />
        {onClose && (
          <IconButton onClick={onClose} sx={headerIconBtnSx} aria-label="Закрыть меню">
            <X size={22} weight="bold" />
          </IconButton>
        )}
      </Box>

      <Box sx={{ px: 1.25, pb: 1.25, flexShrink: 0, display: 'flex', flexDirection: 'column', gap: 0.5 }}>
        <Button
          fullWidth
          startIcon={<Plus size={16} weight="bold" />}
          onClick={onCreate}
          sx={{
            justifyContent: 'flex-start',
            color: 'primary.contrastText',
            bgcolor: 'primary.main',
            borderRadius: '12px',
            textTransform: 'none',
            fontWeight: 600,
            fontSize: '0.875rem',
            px: 1.4,
            py: 1,
            boxShadow: 'var(--bt-halo)',
            '&:hover': { bgcolor: 'primary.dark', boxShadow: 'var(--bt-halo-strong)' },
            '&:active': { transform: 'scale(0.98)' },
          }}
        >
          Новый вопрос
        </Button>
      </Box>

      {conversations.length > 5 && (
        <Box sx={{ px: 1.25, pb: 1.25, flexShrink: 0 }}>
          <TextField
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Найти беседу"
            size="small"
            fullWidth
            InputProps={{
              startAdornment: (
                <Box sx={{ color: 'text.secondary', display: 'flex', mr: 0.75 }}>
                  <MagnifyingGlass size={15} />
                </Box>
              ),
            }}
            sx={{
              '& .MuiOutlinedInput-root': {
                borderRadius: '12px',
                bgcolor: 'var(--bt-overlay-faint)',
                fontSize: '0.875rem',
                color: 'text.primary',
                '& fieldset': { borderColor: 'var(--bt-hairline)' },
                '&:hover fieldset': { borderColor: 'var(--bt-line)' },
                '&.Mui-focused fieldset': { borderColor: 'primary.main' },
              },
              '& input::placeholder': { color: 'text.secondary', opacity: 1 },
            }}
          />
        </Box>
      )}

      <Box
        sx={{
          px: 2,
          pt: 0.5,
          pb: 0.85,
          flexShrink: 0,
          display: 'flex',
          alignItems: 'center',
          gap: 0.75,
          color: 'text.secondary',
          fontSize: '0.75rem',
          fontWeight: 600,
          letterSpacing: '0.02em',
        }}
      >
        <ClockCounterClockwise size={14} />
        Недавние
      </Box>
      <List
        sx={{
          flexGrow: 1,
          minHeight: 0,
          overflow: 'auto',
          overflowX: 'hidden',
          overscrollBehavior: 'contain',
          py: 0,
          px: 1,
          '&::-webkit-scrollbar': { width: 8 },
          '&::-webkit-scrollbar-thumb': {
            bgcolor: 'var(--bt-overlay-strong)',
            borderRadius: 8,
            border: '2px solid transparent',
            backgroundClip: 'padding-box',
          },
        }}
      >
        {search.trim() && filteredConversations.length === 0 && (
          <Typography sx={{ color: 'text.secondary', px: 1.25, py: 1, fontSize: '0.8125rem' }}>
            Ничего не найдено
          </Typography>
        )}
        {!conversations.length && (
          <Box sx={{ px: 1.25, py: 1.5 }}>
            <Typography sx={{ color: 'text.primary', fontSize: '0.875rem', fontWeight: 600, mb: 0.4 }}>
              Пока пусто
            </Typography>
            <Typography sx={{ color: 'text.secondary', fontSize: '0.8125rem', lineHeight: 1.45 }}>
              Нажмите «Новый вопрос» или просто напишите в поле справа.
            </Typography>
          </Box>
        )}
        <AnimatePresence initial={false}>
          {filteredConversations.map((conv, i) => {
            const active = conv.id === activeId;
            return (
              <motion.div
                key={conv.id}
                initial={reduce ? false : { opacity: 0, y: 6 }}
                animate={{ opacity: 1, y: 0 }}
                exit={reduce ? undefined : { opacity: 0 }}
                transition={{ delay: reduce ? 0 : Math.min(i, 8) * 0.03, duration: 0.22, ease: [0.23, 1, 0.32, 1] }}
              >
                <ListItemButton
                  selected={active}
                  onClick={() => onSelect(conv.id)}
                  sx={{
                    position: 'relative',
                    borderRadius: '12px',
                    px: 1.35,
                    py: 1,
                    mb: 0.4,
                    overflow: 'hidden',
                    color: active ? 'text.primary' : 'text.secondary',
                    border: '1px solid',
                    borderColor: active ? 'var(--bt-line)' : 'transparent',
                    bgcolor: active ? 'var(--bt-glow)' : 'transparent',
                    boxShadow: active ? '0 0 22px var(--bt-glow)' : 'none',
                    transition: 'background-color 0.18s cubic-bezier(0.23, 1, 0.32, 1), border-color 0.18s cubic-bezier(0.23, 1, 0.32, 1), box-shadow 0.18s cubic-bezier(0.23, 1, 0.32, 1), color 0.18s cubic-bezier(0.23, 1, 0.32, 1)',
                    '&::before': {
                      content: '""',
                      position: 'absolute',
                      left: 0,
                      top: 10,
                      bottom: 10,
                      width: 2,
                      borderRadius: 2,
                      bgcolor: 'primary.main',
                      boxShadow: '0 0 10px var(--bt-glow-strong)',
                      opacity: active ? 1 : 0,
                      transform: active ? 'scaleY(1)' : 'scaleY(0.4)',
                      transition: 'opacity 0.18s cubic-bezier(0.23, 1, 0.32, 1), transform 0.18s cubic-bezier(0.23, 1, 0.32, 1)',
                    },
                    '&.Mui-selected': {
                      bgcolor: 'var(--bt-glow)',
                      '&:hover': { bgcolor: 'var(--bt-glow-strong)' },
                    },
                    '&:hover': {
                      bgcolor: active ? 'var(--bt-glow-strong)' : 'var(--bt-overlay-faint)',
                      color: 'text.primary',
                    },
                  }}
                >
                  <Box sx={{ flexGrow: 1, minWidth: 0, mr: 0.5, pl: 0.4 }}>
                    {editingId === conv.id ? (
                      <TextField
                        value={editTitle}
                        onChange={(e) => setEditTitle(e.target.value)}
                        size="small"
                        fullWidth
                        autoFocus
                        onClick={(e) => e.stopPropagation()}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') saveEdit();
                          if (e.key === 'Escape') setEditingId(null);
                        }}
                        InputProps={{
                          endAdornment: (
                            <Box sx={{ display: 'flex' }}>
                              <IconButton size="small" onClick={(e) => { e.stopPropagation(); saveEdit(); }} aria-label="Сохранить название" sx={actionBtnSx}>
                                <Check size={14} />
                              </IconButton>
                              <IconButton size="small" onClick={(e) => { e.stopPropagation(); setEditingId(null); }} aria-label="Отменить редактирование" sx={actionBtnSx}>
                                <X size={14} />
                              </IconButton>
                            </Box>
                          ),
                        }}
                      />
                    ) : (
                      <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75, minWidth: 0 }}>
                        {generatingIds.includes(conv.id) && (
                          <Box
                            aria-hidden
                            sx={{
                              width: 8,
                              height: 8,
                              borderRadius: '50%',
                              flexShrink: 0,
                              bgcolor: 'primary.main',
                              boxShadow: '0 0 10px var(--bt-glow-strong)',
                              '@media (prefers-reduced-motion: no-preference)': {
                                animation: 'sidebarJobPulse 1.6s ease-in-out infinite',
                              },
                              '@keyframes sidebarJobPulse': {
                                '0%, 100%': { opacity: 0.35 },
                                '50%': { opacity: 1 },
                              },
                            }}
                          />
                        )}
                        <Box sx={{ minWidth: 0 }}>
                        <Typography
                          sx={{
                            fontWeight: active ? 600 : 500,
                            fontSize: '0.875rem',
                            lineHeight: 1.35,
                            color: 'inherit',
                            whiteSpace: 'nowrap',
                            overflow: 'hidden',
                            textOverflow: 'ellipsis',
                          }}
                        >
                          {conv.title}
                        </Typography>
                        {conv.shared && (
                          <Typography sx={{ fontSize: '0.6875rem', color: 'text.secondary', lineHeight: 1.2 }}>
                            Общий
                          </Typography>
                        )}
                        </Box>
                      </Box>
                    )}
                  </Box>
                  {editingId !== conv.id && conv.role !== 'member' && (
                    <Box
                      sx={{
                        display: 'flex',
                        gap: 0.15,
                        opacity: { xs: 1, md: 0 },
                        '.MuiListItemButton-root:hover &, .MuiListItemButton-root:focus-within &': { opacity: 1 },
                        transition: 'opacity 0.18s cubic-bezier(0.23, 1, 0.32, 1)',
                      }}
                    >
                      <IconButton size="small" onClick={(e) => { e.stopPropagation(); startEdit(conv); }} aria-label="Переименовать беседу" sx={actionBtnSx}>
                        <PencilSimple size={15} />
                      </IconButton>
                      <IconButton
                        size="small"
                        onClick={(e) => { e.stopPropagation(); setConfirmDelete(conv); }}
                        aria-label="Удалить беседу"
                        sx={{ ...actionBtnSx, '&:hover': { color: 'var(--bt-danger)', bgcolor: 'var(--bt-danger-soft)' } }}
                      >
                        <Trash size={15} />
                      </IconButton>
                    </Box>
                  )}
                </ListItemButton>
              </motion.div>
            );
          })}
        </AnimatePresence>
      </List>

      <Dialog
        open={!!confirmDelete}
        onClose={() => setConfirmDelete(null)}
        PaperProps={{
          sx: {
            bgcolor: 'surface.elevated',
            backgroundImage: 'none',
            border: '1px solid var(--bt-hairline)',
            borderRadius: '16px',
            boxShadow: '0 24px 60px var(--bt-scrim), 0 0 28px var(--bt-glow)',
          },
        }}
      >
        <DialogTitle sx={{ color: 'text.primary' }}>Удалить беседу?</DialogTitle>
        <DialogContent>
          <DialogContentText sx={{ color: 'text.secondary' }}>
            «{confirmDelete?.title}» будет удалена без возможности восстановления.
          </DialogContentText>
        </DialogContent>
        <DialogActions sx={{ px: 3, pb: 2 }}>
          <Button onClick={() => setConfirmDelete(null)} sx={{ color: 'text.secondary' }}>
            Отмена
          </Button>
          <Button
            color="error"
            onClick={() => {
              if (confirmDelete) onDelete(confirmDelete.id);
              setConfirmDelete(null);
            }}
          >
            Удалить
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
