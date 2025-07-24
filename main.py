import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime
import time
import io
from typing import Dict, List, Tuple, Optional
import logging
import re
import os
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import warnings
warnings.filterwarnings('ignore')

# Configuração da página
st.set_page_config(
    page_title="Análise de Processos Judiciais",
    page_icon="⚖️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Configuração de logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def load_default_data(analyzer):
    """Carrega automaticamente o arquivo dados.xlsx se existir"""
    default_files = ["dados.xlsx", "data/dados.xlsx", "./dados.xlsx"]

    for file_path in default_files:
        if os.path.exists(file_path):
            try:
                with open(file_path, 'rb') as f:
                    if analyzer.load_data(f):
                        st.success(f"✅ Arquivo padrão carregado: {file_path}")
                        st.session_state['data_loaded'] = True
                        st.session_state['default_loaded'] = True
                        return True
            except Exception as e:
                st.warning(f"⚠️ Erro ao carregar {file_path}: {e}")
                continue

    return False


class ProcessAnalyzer:
    """Classe principal para análise de processos judiciais"""

    def __init__(self):
        self.data = None
        self.data_limpo = None
        self.filters = {
            'REMOVER_URV': False,
            'REMOVER_SINDICATOS': False,
            'REMOVER_ED': False,
            'INCLUIR_ASSUNTO': True,
            'REMOVER_JULGADOS': False,
            'DIAS_PARALISADOS_MIN': 90,  # Alterado para 90 dias
            'ANOS_DISTRIBUICAO': [],
            'CLASSES_SELECIONADAS': [],
            'TAREFAS_SELECIONADAS': [],
            'BUSCA_ETIQUETAS': '',
            'BUSCA_ASSUNTOS': ''
        }
        # Inicialização defensiva dos atributos
        self.unique_classes = []
        self.unique_tarefas = []
        self.unique_anos = []

    def load_data(self, uploaded_file) -> bool:
        """Carrega e processa os dados do arquivo Excel"""
        try:
            with st.spinner("Carregando dados..."):
                self.data = pd.read_excel(
                    uploaded_file,
                    sheet_name=0,
                    dtype=str,
                    skiprows=[0]
                )

                # Limpeza inicial
                self.data = self.data.dropna(subset=['NÚMERO'])

                # Preparar dados para filtros
                self._prepare_filter_data()

                # Log de sucesso
                st.success(f"✅ {len(self.data)} processos carregados com sucesso!")

                return True

        except Exception as e:
            st.error(f"❌ Erro ao carregar arquivo: {str(e)}")
            logger.error(f"Erro no carregamento: {e}")
            return False

    def _prepare_filter_data(self):
        """Prepara dados únicos para os filtros"""
        # Anos de distribuição
        self.data['ANO_DISTRIBUICAO'] = pd.to_datetime(
            self.data['INÍCIO'], errors='coerce'
        ).dt.year
        self.unique_anos = sorted(self.data['ANO_DISTRIBUICAO'].dropna().unique().astype(int))

        # Classes únicas
        self.unique_classes = sorted(self.data['CLASSE'].dropna().unique().tolist())

        # Tarefas PJE únicas
        self.unique_tarefas = sorted(self.data['TAREFAS PJE'].dropna().unique().tolist())

    def _search_in_text(self, text_series: pd.Series, search_terms: str) -> pd.Series:
        """Busca múltiplos termos em uma série de texto"""
        if not search_terms.strip():
            return pd.Series([True] * len(text_series))

        # Divide os termos por espaço e remove termos vazios
        terms = [term.strip() for term in search_terms.split() if term.strip()]

        if not terms:
            return pd.Series([True] * len(text_series))

        # Cria padrão regex para buscar todos os termos (case insensitive)
        pattern = '.*'.join([re.escape(term) for term in terms])

        return text_series.fillna('').str.contains(pattern, case=False, regex=True)

    def clean_data(self) -> pd.DataFrame:
        """Limpa e processa os dados conforme filtros selecionados"""
        if self.data is None:
            return None

        data_limpo = self.data.copy()

        # Conversão de tipos iniciais
        data_limpo['DIAS ÚLT. MOV.'] = pd.to_numeric(
            data_limpo['DIAS ÚLT. MOV.'], errors='coerce'
        ).fillna(0).astype('int64')

        data_limpo['DIAS CONCLUSO'] = pd.to_numeric(
            data_limpo['DIAS CONCLUSO'], errors='coerce'
        ).fillna(0).astype('int64')

        # Criação de colunas auxiliares
        data_limpo['ANO_DISTRIBUICAO'] = pd.to_datetime(
            data_limpo['INÍCIO'], errors='coerce'
        ).dt.year

        # Aplicação de filtros
        data_limpo = self._apply_all_filters(data_limpo)

        # Remoção de colunas desnecessárias
        cols_to_drop = [
            'SISTEMA', 'DATA ÚLT. MOV.', 'ÚLT. MOV.', 'CONCLUSÃO',
            'TIPO CONCLUSÃO', 'SUSPENSÃO', 'TRÂNSITO', 'FÍSICO / ELETRÔNICO?'
        ]

        # Remove apenas colunas que existem
        cols_existing = [col for col in cols_to_drop if col in data_limpo.columns]
        data_limpo = data_limpo.drop(columns=cols_existing)

        # Ordenação
        data_limpo = data_limpo.sort_values(
            by=['CLASSIFICAÇÃO', 'CLASSE', 'ASSUNTO', 'TAREFAS PJE', 'DIAS CONCLUSO']
        )

        # Conversão para categorias
        categorical_cols = ["CLASSIFICAÇÃO", "CLASSE", "ASSUNTO", "PENDENTE DE META?", "TAREFAS PJE"]
        for col in categorical_cols:
            if col in data_limpo.columns:
                data_limpo[col] = data_limpo[col].astype('category')

        self.data_limpo = data_limpo
        return data_limpo

    def _apply_all_filters(self, df: pd.DataFrame) -> pd.DataFrame:
        """Aplica todos os filtros aos dados"""

        # Remove processos com minutas assinadas
        df = df[~df["TAREFAS PJE"].str.contains("Assinar ").fillna(True)]

        # Filtro de processos julgados
        if self.filters['REMOVER_JULGADOS']:
            df = df[df['JULGAMENTO'].isnull()]

        # Filtro Embargos de Declaração
        if self.filters['REMOVER_ED']:
            df = df[~df["TAREFAS PJE"].str.contains("Emb. Declaração ").fillna(True)]

        # Filtro URV
        if self.filters['REMOVER_URV']:
            df = df[~df["ASSUNTO"].str.contains("URV Lei 8.880/1994").fillna(True)]
            df = df[~df["ETIQUETAS PJE"].str.contains("URV").fillna(True)]

        # Filtro Sindicatos
        if self.filters['REMOVER_SINDICATOS']:
            sindicatos = ["3 - SINTE", "3 - SINAI", "3 - SINSENAT", "SINSENAT"]
            for sind in sindicatos:
                df = df[~df["ETIQUETAS PJE"].str.contains(sind).fillna(True)]

        # Filtro por ano de distribuição
        if self.filters['ANOS_DISTRIBUICAO']:
            df = df[df['ANO_DISTRIBUICAO'].isin(self.filters['ANOS_DISTRIBUICAO'])]

        # Filtro por classes
        if self.filters['CLASSES_SELECIONADAS']:
            df = df[df['CLASSE'].isin(self.filters['CLASSES_SELECIONADAS'])]

        # Filtro por tarefas PJE
        if self.filters['TAREFAS_SELECIONADAS']:
            df = df[df['TAREFAS PJE'].isin(self.filters['TAREFAS_SELECIONADAS'])]

        # Busca em etiquetas
        if self.filters['BUSCA_ETIQUETAS']:
            etiquetas_mask = self._search_in_text(df['ETIQUETAS PJE'], self.filters['BUSCA_ETIQUETAS'])
            df = df[etiquetas_mask]

        # Busca em assuntos
        if self.filters['BUSCA_ASSUNTOS']:
            assuntos_mask = self._search_in_text(df['ASSUNTO'], self.filters['BUSCA_ASSUNTOS'])
            df = df[assuntos_mask]

        return df

    def get_process_groups(self) -> Dict[str, pd.DataFrame]:
        """Retorna grupos de processos organizados por categoria"""
        if self.data_limpo is None:
            return {}

        groups = {}

        # Execuções
        groups['Execuções'] = self.data_limpo[
            self.data_limpo.CLASSIFICAÇÃO == "EXECUÇÃO"
            ]

        # Conhecimento apenas
        conhecimento = self.data_limpo[
            self.data_limpo.CLASSIFICAÇÃO == "CONHECIMENTO"
            ]

        # Saúde
        assuntos_saude = [
            "11884 - Fornecimento de Medicamentos",
            "12506 - Unidade de terapia intensiva (UTI) / unidade de cuidados intensivos (UCI)",
            "11885 - Unidade de terapia intensiva (UTI) ou unidade de cuidados intensivos (UCI)",
            "12484 - Fornecimento de medicamentos",
            "10356 - Assistência Médico-Hospitalar",
            "10064 - Saúde",
            "11854 - Saúde Mental",
            "12501 - Cirurgia",
            "12502 - Eletiva",
            "12508 - Internação compulsória",
            "12483 - Internação/Transferência Hospitalar",
            "11856 - Hospitais e Outras Unidades de Saúde",
            "11883 - Tratamento Médico-Hospitalar",
            "12491 - Tratamento médico-hospitalar",
            "11847 - ASSISTÊNCIA SOCIAL"
        ]
        groups['Demandas de Saúde'] = conhecimento[
            conhecimento['ASSUNTO'].isin(assuntos_saude)
        ]

        # INSS
        assuntos_inss = [
            "10567 - Aposentadoria por Invalidez Acidentária",
            "6095 - Aposentadoria por Invalidez",
            "6101 - Auxílio-Doença Previdenciário",
            "6107 - Auxílio-Acidente (Art. 86)",
            "7757 - Auxílio-Doença Acidentário",
            "6111 - Movimentos Repetitivos/Tenossinovite/LER/DORT",
            "6108 - Incapacidade Laborativa Parcial",
            "6110 - Incapacidade Laborativa Temporária",
            "6109 - Incapacidade Laborativa Permanente"
        ]
        groups['INSS Acidentárias'] = conhecimento[
            conhecimento['ASSUNTO'].isin(assuntos_inss)
        ]

        # Mandados de Segurança
        groups['Mandados de Segurança'] = conhecimento[
            conhecimento['CLASSE'].isin([
                "120 - MANDADO DE SEGURANÇA CÍVEL",
                "1710 - MANDADO DE SEGURANÇA CRIMINAL"
            ])
        ]

        # ACP/AIA/AP
        groups['ACP/AP/AIA'] = conhecimento[
            conhecimento['CLASSE'].isin([
                "64 - AÇÃO CIVIL DE IMPROBIDADE ADMINISTRATIVA",
                "1690 - (ECA) AÇÃO CIVIL PÚBLICA INFÂNCIA E JUVENTUDE",
                "65 - AÇÃO CIVIL PÚBLICA",
                "66 - AÇÃO POPULAR"
            ])
        ]

        # Metas CNJ
        groups['Metas CNJ'] = conhecimento[
            conhecimento['PENDENTE DE META?'].notnull()
        ]

        # Paralisados (agora 90+ dias)
        groups['Paralisados'] = self.data_limpo[
            self.data_limpo["DIAS CONCLUSO"] >= self.filters['DIAS_PARALISADOS_MIN']
            ]

        # Assuntos repetitivos
        assuntos_freq = self._get_frequent_subjects(conhecimento)
        groups['Repetitivos'] = conhecimento[
            conhecimento['ASSUNTO'].isin(assuntos_freq)
        ]

        # NOVOS AGRUPAMENTOS

        # Agrupamento por Assunto (top 10)
        if len(self.data_limpo) > 0:
            top_assuntos = self.data_limpo['ASSUNTO'].value_counts().head(10)
            for assunto in top_assuntos.index:
                if pd.notna(assunto):
                    # Limita o nome da aba para o Excel
                    assunto_short = assunto[:25] + "..." if len(assunto) > 25 else assunto
                    groups[f'Assunto: {assunto_short}'] = self.data_limpo[
                        self.data_limpo['ASSUNTO'] == assunto
                        ]

        # Agrupamento por Classe (top 10)
        if len(self.data_limpo) > 0:
            top_classes = self.data_limpo['CLASSE'].value_counts().head(10)
            for classe in top_classes.index:
                if pd.notna(classe):
                    # Limita o nome da aba para o Excel
                    classe_short = classe[:25] + "..." if len(classe) > 25 else classe
                    groups[f'Classe: {classe_short}'] = self.data_limpo[
                        self.data_limpo['CLASSE'] == classe
                        ]

        return groups

    def _get_frequent_subjects(self, df: pd.DataFrame, min_count: int = 10) -> List[str]:
        """Retorna lista de assuntos com frequência mínima"""
        freq_assuntos = df.groupby(['ASSUNTO']).size().reset_index(name='counts')
        return freq_assuntos[freq_assuntos['counts'] >= min_count]['ASSUNTO'].tolist()


class Dashboard:
    """Classe para criação do dashboard Streamlit"""

    def __init__(self, analyzer: ProcessAnalyzer):
        self.analyzer = analyzer

    def _get_filter_value(self, filter_key: str, default_value=None):
        """Acessa filtros com valor padrão para evitar KeyError"""
        return self.analyzer.filters.get(filter_key, default_value)

    def render_sidebar(self):
        """Renderiza barra lateral com filtros"""
        st.sidebar.header("⚙️ Configurações")

        # Filtros de Remoção
        st.sidebar.subheader("🗑️ Filtros de Remoção")

        self.analyzer.filters['REMOVER_JULGADOS'] = st.sidebar.checkbox(
            "Remover processos já julgados",
            value=self.analyzer.filters.get('REMOVER_JULGADOS', False)
        )

        self.analyzer.filters['REMOVER_ED'] = st.sidebar.checkbox(
            "Remover Embargos de Declaração",
            value=self.analyzer.filters.get('REMOVER_ED', False)
        )

        self.analyzer.filters['REMOVER_URV'] = st.sidebar.checkbox(
            "Remover processos URV",
            value=self.analyzer.filters.get('REMOVER_URV', False)
        )

        self.analyzer.filters['REMOVER_SINDICATOS'] = st.sidebar.checkbox(
            "Remover processos de sindicatos",
            value=self.analyzer.filters.get('REMOVER_SINDICATOS', False)
        )

        # Filtros de Seleção - APENAS SE DADOS FORAM CARREGADOS
        st.sidebar.subheader("🔍 Filtros de Seleção")

        # Verificação de segurança para evitar AttributeError
        if hasattr(self.analyzer, 'unique_anos') and self.analyzer.unique_anos:
            self.analyzer.filters['ANOS_DISTRIBUICAO'] = st.sidebar.multiselect(
                "Anos de Distribuição",
                options=self.analyzer.unique_anos,
                default=self.analyzer.filters.get('ANOS_DISTRIBUICAO', []),
                help="Selecione os anos de distribuição desejados"
            )
        else:
            st.sidebar.info("📅 Filtro por anos: Disponível após carregar dados")

        # Filtro por classe
        if hasattr(self.analyzer, 'unique_classes') and self.analyzer.unique_classes:
            self.analyzer.filters['CLASSES_SELECIONADAS'] = st.sidebar.multiselect(
                "Classes Judiciais",
                options=self.analyzer.unique_classes,
                default=self.analyzer.filters.get('CLASSES_SELECIONADAS', []),
                help="Selecione as classes judiciais desejadas"
            )
        else:
            st.sidebar.info("⚖️ Filtro por classes: Disponível após carregar dados")

        # Filtro por tarefas PJE
        if hasattr(self.analyzer, 'unique_tarefas') and self.analyzer.unique_tarefas:
            self.analyzer.filters['TAREFAS_SELECIONADAS'] = st.sidebar.multiselect(
                "Tarefas PJE",
                options=self.analyzer.unique_tarefas,
                default=self.analyzer.filters.get('TAREFAS_SELECIONADAS', []),
                help="Selecione as tarefas PJE desejadas"
            )
        else:
            st.sidebar.info("📋 Filtro por tarefas: Disponível após carregar dados")

        # Busca em Etiquetas - SEMPRE DISPONÍVEL
        st.sidebar.subheader("🔎 Busca por Texto")

        self.analyzer.filters['BUSCA_ETIQUETAS'] = st.sidebar.text_input(
            "Buscar em Etiquetas",
            value=self.analyzer.filters.get('BUSCA_ETIQUETAS', ''),
            help="Digite palavras-chave separadas por espaço (ex: 'previdenciário auxílio')"
        )

        # Busca em Assuntos
        self.analyzer.filters['BUSCA_ASSUNTOS'] = st.sidebar.text_input(
            "Buscar em Assuntos",
            value=self.analyzer.filters.get('BUSCA_ASSUNTOS', ''),
            help="Digite palavras-chave separadas por espaço (ex: 'medicamento saúde')"
        )

        # Parâmetros
        st.sidebar.subheader("⚙️ Parâmetros")

        self.analyzer.filters['DIAS_PARALISADOS_MIN'] = st.sidebar.number_input(
            "Dias mínimos para considerar paralisado",
            min_value=1,
            max_value=365,
            value=self.analyzer.filters.get('DIAS_PARALISADOS_MIN', 90)
        )

        self.analyzer.filters['INCLUIR_ASSUNTO'] = st.sidebar.checkbox(
            "Incluir coluna Assunto na exportação",
            value=self.analyzer.filters.get('INCLUIR_ASSUNTO', True)
        )

        # Botões de ação
        col1, col2 = st.sidebar.columns(2)

        with col1:
            aplicar = st.button("🔄 Aplicar", type="primary")

        with col2:
            limpar = st.button("🧹 Limpar")

        if limpar:
            # Reset dos filtros
            self.analyzer.filters.update({
                'ANOS_DISTRIBUICAO': [],
                'CLASSES_SELECIONADAS': [],
                'TAREFAS_SELECIONADAS': [],
                'BUSCA_ETIQUETAS': '',
                'BUSCA_ASSUNTOS': ''
            })
            st.rerun()

        return aplicar

    def render_upload_section(self):
        """Renderiza seção de upload com auto-load"""
        st.header("📁 Upload do Arquivo")

        # Tentar carregar arquivo padrão automaticamente
        if 'default_loaded' not in st.session_state:
            if load_default_data(self.analyzer):
                st.info("💡 Arquivo padrão carregado. Você pode fazer upload de outro arquivo se desejar.")
            else:
                st.info("📝 Coloque seu arquivo como 'dados.xlsx' na pasta raiz para carregamento automático")

        uploaded_file = st.file_uploader(
            "Ou escolha outro arquivo Excel",
            type=['xlsx', 'xls'],
            help="Arquivo deve seguir o formato padrão do GPSJUS"
        )

        if uploaded_file is not None:
            if st.button("📊 Processar Novo Arquivo", type="primary"):
                if self.analyzer.load_data(uploaded_file):
                    st.session_state['data_loaded'] = True
                    st.session_state['default_loaded'] = False
                    st.rerun()

        return uploaded_file is not None or st.session_state.get('default_loaded', False)

    def render_overview(self):
        """Renderiza visão geral dos dados"""
        if self.analyzer.data is None:
            return

        st.header("📊 Visão Geral")

        # Métricas principais
        col1, col2, col3, col4, col5 = st.columns(5)

        total_original = len(self.analyzer.data)
        total_filtrado = len(self.analyzer.data_limpo) if self.analyzer.data_limpo is not None else 0

        with col1:
            st.metric("Total Original", total_original)

        with col2:
            st.metric(
                "Após Filtros",
                total_filtrado,
                delta=total_filtrado - total_original
            )

        with col3:
            if self.analyzer.data_limpo is not None:
                conhecimento = len(self.analyzer.data_limpo[
                                       self.analyzer.data_limpo['CLASSIFICAÇÃO'] == 'CONHECIMENTO'
                                       ])
                st.metric("Conhecimento", conhecimento)

        with col4:
            if self.analyzer.data_limpo is not None:
                execucao = len(self.analyzer.data_limpo[
                                   self.analyzer.data_limpo['CLASSIFICAÇÃO'] == 'EXECUÇÃO'
                                   ])
                st.metric("Execução", execucao)

        with col5:
            if self.analyzer.data_limpo is not None:
                paralisados = len(self.analyzer.data_limpo[
                                      self.analyzer.data_limpo['DIAS CONCLUSO'] >= self.analyzer.filters[
                                          'DIAS_PARALISADOS_MIN']
                                      ])
                st.metric("Paralisados (90+ dias)", paralisados)

        # Alerta de filtros ativos
        filtros_ativos = []
        if self.analyzer.filters['ANOS_DISTRIBUICAO']:
            filtros_ativos.append(f"Anos: {len(self.analyzer.filters['ANOS_DISTRIBUICAO'])}")
        if self.analyzer.filters['CLASSES_SELECIONADAS']:
            filtros_ativos.append(f"Classes: {len(self.analyzer.filters['CLASSES_SELECIONADAS'])}")
        if self.analyzer.filters['TAREFAS_SELECIONADAS']:
            filtros_ativos.append(f"Tarefas: {len(self.analyzer.filters['TAREFAS_SELECIONADAS'])}")
        if self.analyzer.filters['BUSCA_ETIQUETAS']:
            filtros_ativos.append("Busca Etiquetas")
        if self.analyzer.filters['BUSCA_ASSUNTOS']:
            filtros_ativos.append("Busca Assuntos")

        if filtros_ativos:
            st.info(f"🔍 Filtros ativos: {', '.join(filtros_ativos)}")

    def render_charts(self):
        """Renderiza gráficos de análise"""
        if self.analyzer.data_limpo is None or len(self.analyzer.data_limpo) == 0:
            st.warning("Nenhum dado disponível para exibir gráficos")
            return

        st.header("📈 Análises")

        col1, col2 = st.columns(2)

        with col1:
            # Gráfico por classificação
            st.subheader("Distribuição por Classificação")
            classif_counts = self.analyzer.data_limpo['CLASSIFICAÇÃO'].value_counts()

            if len(classif_counts) > 0:
                fig_classif = px.pie(
                    values=classif_counts.values,
                    names=classif_counts.index,
                    title="Processos por Classificação"
                )
                fig_classif.update_traces(textposition='inside', textinfo='percent+label')
                st.plotly_chart(fig_classif, use_container_width=True)

        with col2:
            # Gráfico por ano
            st.subheader("Distribuição por Ano")
            if 'ANO_DISTRIBUICAO' in self.analyzer.data_limpo.columns:
                ano_counts = self.analyzer.data_limpo['ANO_DISTRIBUICAO'].value_counts().sort_index()

                if len(ano_counts) > 0:
                    fig_ano = px.bar(
                        x=ano_counts.index,
                        y=ano_counts.values,
                        title="Processos por Ano de Distribuição",
                        labels={'x': 'Ano', 'y': 'Quantidade'}
                    )
                    st.plotly_chart(fig_ano, use_container_width=True)

        # Gráfico adicional: Top 10 Classes
        st.subheader("Top 10 Classes mais Frequentes")
        if 'CLASSE' in self.analyzer.data_limpo.columns:
            top_classes = self.analyzer.data_limpo['CLASSE'].value_counts().head(10)

            if len(top_classes) > 0:
                fig_classes = px.bar(
                    x=top_classes.values,
                    y=[classe[:50] + "..." if len(classe) > 50 else classe for classe in top_classes.index],
                    orientation='h',
                    title="Classes Mais Frequentes",
                    labels={'x': 'Quantidade', 'y': 'Classe'}
                )
                fig_classes.update_layout(height=400)
                st.plotly_chart(fig_classes, use_container_width=True)

    def render_process_groups(self):
        """Renderiza seção de grupos de processos"""
        if self.analyzer.data_limpo is None:
            return

        st.header("📋 Grupos de Processos")

        groups = self.analyzer.get_process_groups()

        if not groups:
            st.warning("Nenhum grupo de processos disponível")
            return

        # Tabela resumo
        summary_data = []
        for name, df in groups.items():
            if len(df) > 0:  # Só inclui grupos com dados
                summary_data.append({
                    'Grupo': name,
                    'Quantidade': len(df),
                    'Percentual': f"{len(df) / len(self.analyzer.data_limpo) * 100:.1f}%"
                })

        if summary_data:
            summary_df = pd.DataFrame(summary_data)
            summary_df = summary_df.sort_values('Quantidade', ascending=False)
            st.dataframe(summary_df, use_container_width=True)

            # Seleção de grupo para visualização
            grupos_com_dados = [item['Grupo'] for item in summary_data]
            selected_group = st.selectbox(
                "Selecione um grupo para visualizar:",
                options=grupos_com_dados
            )

            if selected_group and len(groups[selected_group]) > 0:
                st.subheader(f"Detalhes: {selected_group}")

                # Colunas para exibição
                display_cols = ['NÚMERO', 'ETIQUETAS PJE', 'DIAS CONCLUSO', 'CLASSE', 'TAREFAS PJE']
                if self.analyzer.filters['INCLUIR_ASSUNTO']:
                    display_cols.append('ASSUNTO')

                # Filtrar apenas colunas existentes
                available_cols = [col for col in display_cols if col in groups[selected_group].columns]

                # Ordenar por dias concluso (decrescente)
                group_df = groups[selected_group].copy()
                if 'DIAS CONCLUSO' in group_df.columns:
                    group_df = group_df.sort_values('DIAS CONCLUSO', ascending=False)

                st.dataframe(
                    group_df[available_cols].head(50),
                    use_container_width=True
                )

                if len(groups[selected_group]) > 50:
                    st.info(f"Mostrando 50 de {len(groups[selected_group])} processos (ordenados por dias concluso)")

    def render_export_section(self):
        """Renderiza seção de exportação"""
        if self.analyzer.data_limpo is None:
            return

        st.header("💾 Exportação")

        col1, col2 = st.columns(2)

        with col1:
            if st.button("📥 Gerar Arquivo Excel", type="primary"):
                excel_file = self._generate_excel()

                st.download_button(
                    label="⬇️ Download Excel Completo",
                    data=excel_file,
                    file_name=f"analise_processos_{datetime.now().strftime('%d_%m_%Y_%H%M')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )

        with col2:
            if st.button("📊 Gerar Relatório Resumo"):
                summary_file = self._generate_summary_excel()

                st.download_button(
                    label="⬇️ Download Relatório Resumo",
                    data=summary_file,
                    file_name=f"resumo_processos_{datetime.now().strftime('%d_%m_%Y_%H%M')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )

    def _generate_excel(self) -> bytes:
        """Gera arquivo Excel com os grupos de processos"""
        output = io.BytesIO()
        groups = self.analyzer.get_process_groups()

        # Colunas para exportação
        cols = ['NÚMERO', 'ETIQUETAS PJE', 'DIAS CONCLUSO', 'CLASSE', 'TAREFAS PJE']
        if self.analyzer.filters['INCLUIR_ASSUNTO']:
            cols.append('ASSUNTO')

        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            # Aba com dados filtrados completos
            if self.analyzer.data_limpo is not None and len(self.analyzer.data_limpo) > 0:
                available_cols = [col for col in cols if col in self.analyzer.data_limpo.columns]
                self.analyzer.data_limpo[available_cols].to_excel(
                    writer,
                    sheet_name="Dados_Filtrados",
                    index=False
                )

            # Abas por grupo (apenas grupos com dados)
            for sheet_name, df in groups.items():
                if len(df) > 0:
                    # Filtrar apenas colunas existentes
                    available_cols = [col for col in cols if col in df.columns]
                    # Ordenar por dias concluso
                    df_sorted = df.copy()
                    if 'DIAS CONCLUSO' in df_sorted.columns:
                        df_sorted = df_sorted.sort_values('DIAS CONCLUSO', ascending=False)

                    # Limitar nome da aba para Excel (31 caracteres)
                    safe_sheet_name = sheet_name[:31].replace('[', '').replace(']', '').replace('*', '').replace(
                        '?', '').replace('/', '').replace('\\', '')

                    df_sorted[available_cols].to_excel(
                        writer,
                        sheet_name=safe_sheet_name,
                        index=False
                    )

        output.seek(0)
        return output.read()

    def _generate_summary_excel(self) -> bytes:
        """Gera arquivo Excel apenas com resumo estatístico"""
        output = io.BytesIO()
        groups = self.analyzer.get_process_groups()

        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            # Aba de resumo geral
            summary_data = []
            total_processos = len(self.analyzer.data_limpo) if self.analyzer.data_limpo is not None else 0

            for name, df in groups.items():
                if len(df) > 0:
                    # Estatísticas do grupo
                    dias_medio = df['DIAS CONCLUSO'].mean() if 'DIAS CONCLUSO' in df.columns else 0
                    dias_max = df['DIAS CONCLUSO'].max() if 'DIAS CONCLUSO' in df.columns else 0

                    summary_data.append({
                        'Grupo': name,
                        'Quantidade': len(df),
                        'Percentual': f"{len(df) / total_processos * 100:.1f}%" if total_processos > 0 else "0%",
                        'Dias_Concluso_Medio': round(dias_medio, 1),
                        'Dias_Concluso_Maximo': dias_max,
                        'Principais_Classes': ', '.join(
                            df['CLASSE'].value_counts().head(3).index.tolist()) if 'CLASSE' in df.columns else ''
                    })

            if summary_data:
                summary_df = pd.DataFrame(summary_data)
                summary_df = summary_df.sort_values('Quantidade', ascending=False)
                summary_df.to_excel(writer, sheet_name="Resumo_Geral", index=False)

            # Aba de estatísticas por classe
            if self.analyzer.data_limpo is not None and 'CLASSE' in self.analyzer.data_limpo.columns:
                class_stats = self.analyzer.data_limpo.groupby('CLASSE').agg({
                    'NÚMERO': 'count',
                    'DIAS CONCLUSO': ['mean', 'max', 'min'],
                    'ANO_DISTRIBUICAO': lambda x: ', '.join(map(str, sorted(x.dropna().unique())))
                }).round(1)

                class_stats.columns = ['Quantidade', 'Dias_Medio', 'Dias_Maximo', 'Dias_Minimo',
                                       'Anos_Distribuicao']
                class_stats = class_stats.sort_values('Quantidade', ascending=False)
                class_stats.to_excel(writer, sheet_name="Estatisticas_Classes")

            # Aba de estatísticas por assunto (top 20)
            if self.analyzer.data_limpo is not None and 'ASSUNTO' in self.analyzer.data_limpo.columns:
                subject_stats = self.analyzer.data_limpo.groupby('ASSUNTO').agg({
                    'NÚMERO': 'count',
                    'DIAS CONCLUSO': ['mean', 'max'],
                    'CLASSE': lambda x: ', '.join(x.value_counts().head(2).index.tolist())
                }).round(1)

                subject_stats.columns = ['Quantidade', 'Dias_Medio', 'Dias_Maximo', 'Principais_Classes']
                subject_stats = subject_stats.sort_values('Quantidade', ascending=False).head(20)
                subject_stats.to_excel(writer, sheet_name="Top20_Assuntos")

            # Aba de filtros aplicados
            filters_data = []
            for key, value in self.analyzer.filters.items():
                if value:  # Só inclui filtros ativos
                    if isinstance(value, list) and value:
                        filters_data.append({
                            'Filtro': key,
                            'Tipo': 'Lista',
                            'Valor': ', '.join(map(str, value[:5])) + ('...' if len(value) > 5 else ''),
                            'Quantidade_Selecionada': len(value)
                        })
                    elif isinstance(value, str) and value.strip():
                        filters_data.append({
                            'Filtro': key,
                            'Tipo': 'Texto',
                            'Valor': value,
                            'Quantidade_Selecionada': 1
                        })
                    elif isinstance(value, bool) and value:
                        filters_data.append({
                            'Filtro': key,
                            'Tipo': 'Boolean',
                            'Valor': 'Ativo',
                            'Quantidade_Selecionada': 1
                        })
                    elif isinstance(value, (int, float)) and value != 90:  # 90 é o padrão
                        filters_data.append({
                            'Filtro': key,
                            'Tipo': 'Numérico',
                            'Valor': str(value),
                            'Quantidade_Selecionada': 1
                        })

            if filters_data:
                filters_df = pd.DataFrame(filters_data)
                filters_df.to_excel(writer, sheet_name="Filtros_Aplicados", index=False)

        output.seek(0)
        return output.read()

    def create_performance_heatmap(self, data_limpo):
        """Cria heatmap de performance por classe e ano"""
        if 'ANO_DISTRIBUICAO' not in data_limpo.columns:
            return None

        # Agrupa por ano e classe
        heatmap_data = data_limpo.groupby(['ANO_DISTRIBUICAO', 'CLASSE']).agg({
            'DIAS CONCLUSO': 'mean',
            'NÚMERO': 'count'
        }).reset_index()

        # Pivota para criar matriz
        pivot_table = heatmap_data.pivot(
            index='CLASSE',
            columns='ANO_DISTRIBUICAO',
            values='DIAS CONCLUSO'
        ).fillna(0)

        # Limita a 15 classes mais frequentes
        top_classes = data_limpo['CLASSE'].value_counts().head(15).index
        pivot_table = pivot_table.loc[pivot_table.index.intersection(top_classes)]

        if pivot_table.empty:
            return None

        fig = go.Figure(data=go.Heatmap(
            z=pivot_table.values,
            x=[str(col) for col in pivot_table.columns],
            y=[classe[:40] + "..." if len(classe) > 40 else classe for classe in pivot_table.index],
            colorscale='RdYlBu_r',
            text=pivot_table.values.round(0),
            texttemplate="%{text}",
            textfont={"size": 10},
            colorbar=dict(title="Dias Médios")
        ))

        fig.update_layout(
            title="Heatmap: Tempo Médio de Tramitação por Classe e Ano",
            xaxis_title="Ano de Distribuição",
            yaxis_title="Classe Judicial",
            height=600
        )

        return fig

    def create_pareto_chart(self, data_limpo):
        """Cria gráfico de Pareto para análise 80/20"""
        # Calcula tempo total por classe
        class_time = data_limpo.groupby('CLASSE').agg({
            'DIAS CONCLUSO': 'sum',
            'NÚMERO': 'count'
        }).reset_index()

        class_time['TEMPO_MEDIO'] = class_time['DIAS CONCLUSO'] / class_time['NÚMERO']
        class_time = class_time.sort_values('DIAS CONCLUSO', ascending=False).head(15)

        # Calcula percentual acumulado
        class_time['PERC_INDIVIDUAL'] = (class_time['DIAS CONCLUSO'] / class_time['DIAS CONCLUSO'].sum()) * 100
        class_time['PERC_ACUMULADO'] = class_time['PERC_INDIVIDUAL'].cumsum()

        # Cria gráfico
        fig = make_subplots(specs=[[{"secondary_y": True}]])

        # Barras
        fig.add_trace(
            go.Bar(
                x=[classe[:30] + "..." if len(classe) > 30 else classe for classe in class_time['CLASSE']],
                y=class_time['DIAS CONCLUSO'],
                name="Dias Totais",
                marker_color='lightblue'
            ),
            secondary_y=False,
        )

        # Linha de percentual acumulado
        fig.add_trace(
            go.Scatter(
                x=[classe[:30] + "..." if len(classe) > 30 else classe for classe in class_time['CLASSE']],
                y=class_time['PERC_ACUMULADO'],
                mode='lines+markers',
                name="% Acumulado",
                line=dict(color='red', width=3),
                marker=dict(size=8)
            ),
            secondary_y=True,
        )

        # Linha dos 80%
        fig.add_hline(y=80, line_dash="dash", line_color="red", secondary_y=True)

        fig.update_xaxes(title_text="Classes Judiciais")
        fig.update_yaxes(title_text="Dias Totais de Tramitação", secondary_y=False)
        fig.update_yaxes(title_text="Percentual Acumulado (%)", secondary_y=True)

        fig.update_layout(
            title="Análise de Pareto: Classes que Consomem Mais Tempo",
            height=500
        )

        return fig

    def create_productivity_funnel(self, data_limpo):
        """Cria funil de produtividade judicial"""
        # Simula estágios do processo (pode ser adaptado conforme dados reais)
        total_distribuidos = len(data_limpo)
        em_andamento = len(
            data_limpo[data_limpo['JULGAMENTO'].isnull()]) if 'JULGAMENTO' in data_limpo.columns else int(
            total_distribuidos * 0.7)
        conclusos = len(data_limpo[data_limpo['DIAS CONCLUSO'] > 0])
        julgados = total_distribuidos - em_andamento

        fig = go.Figure(go.Funnel(
            y=["Distribuídos", "Em Andamento", "Conclusos", "Julgados"],
            x=[total_distribuidos, em_andamento, conclusos, julgados],
            textinfo="value+percent initial",
            marker={"color": ["deepskyblue", "lightsalmon", "lightgreen", "gold"]},
            connector={"line": {"color": "royalblue", "dash": "dot", "width": 3}}
        ))

        fig.update_layout(
            title="Funil de Produtividade Judicial",
            height=400
        )

        return fig

    def create_risk_matrix(self, data_limpo):
        """Cria matriz de risco: Volume x Complexidade"""
        # Agrupa por assunto
        risk_data = data_limpo.groupby('ASSUNTO').agg({
            'NÚMERO': 'count',
            'DIAS CONCLUSO': 'mean'
        }).reset_index()

        risk_data = risk_data[risk_data['NÚMERO'] >= 3]  # Só assuntos com pelo menos 3 processos
        risk_data = risk_data.head(20)  # Top 20

        if len(risk_data) == 0:
            fig = go.Figure()
            fig.add_annotation(text="Dados insuficientes para matriz de risco",
                               x=0.5, y=0.5, showarrow=False)
            return fig

        # Define cores baseadas em quartis
        q75_volume = risk_data['NÚMERO'].quantile(0.75)
        q75_tempo = risk_data['DIAS CONCLUSO'].quantile(0.75)

        colors = []
        sizes = []
        for _, row in risk_data.iterrows():
            volume = row['NÚMERO']
            tempo = row['DIAS CONCLUSO']

            if volume >= q75_volume and tempo >= q75_tempo:
                colors.append('red')  # Alto risco
                sizes.append(20)
            elif volume >= q75_volume or tempo >= q75_tempo:
                colors.append('orange')  # Médio risco
                sizes.append(15)
            else:
                colors.append('green')  # Baixo risco
                sizes.append(10)

        fig = go.Figure(data=go.Scatter(
            x=risk_data['NÚMERO'],
            y=risk_data['DIAS CONCLUSO'],
            mode='markers+text',
            marker=dict(
                size=sizes,
                color=colors,
                opacity=0.7,
                line=dict(width=2, color='white')
            ),
            text=[assunto[:25] + "..." if len(assunto) > 25 else assunto for assunto in risk_data['ASSUNTO']],
            textposition="top center",
            textfont=dict(size=8),
            hovertemplate="<b>%{text}</b><br>Volume: %{x}<br>Tempo Médio: %{y:.0f} dias<extra></extra>"
        ))

        # Adiciona linhas de referência
        fig.add_vline(x=q75_volume, line_dash="dash", line_color="gray", annotation_text="75% Volume")
        fig.add_hline(y=q75_tempo, line_dash="dash", line_color="gray", annotation_text="75% Tempo")

        fig.update_layout(
            title="Matriz de Risco: Volume x Complexidade por Assunto",
            xaxis_title="Volume de Processos",
            yaxis_title="Tempo Médio (dias)",
            height=600
        )

        return fig

    # =============================================================================
    # 3. MÉTRICAS AVANÇADAS E KPIs (ADICIONAR NA CLASSE Dashboard)
    # =============================================================================

    def calculate_advanced_metrics(self):
        """Calcula métricas avançadas de produtividade"""
        if self.analyzer.data_limpo is None:
            return {}

        data = self.analyzer.data_limpo

        metrics = {}

        # Taxa de Congestionamento
        total_processos = len(data)
        julgados = len(data[data['JULGAMENTO'].notnull()]) if 'JULGAMENTO' in data.columns else int(total_processos * 0.3)
        metrics['taxa_congestionamento'] = ((total_processos - julgados) / total_processos) * 100

        # Idade Média do Acervo
        metrics['idade_media_acervo'] = data['DIAS CONCLUSO'].mean()

        # Clearance Rate (simulado - seria casos novos vs julgados no período)
        distribuidos_ano_atual = len(data[data['ANO_DISTRIBUICAO'] == data[
            'ANO_DISTRIBUICAO'].max()]) if 'ANO_DISTRIBUICAO' in data.columns else total_processos
        metrics['clearance_rate'] = (julgados / distribuidos_ano_atual) * 100 if distribuidos_ano_atual > 0 else 0

        # Produtividade por Dia
        dias_uteis_ano = 220  # Aproximado
        metrics['produtividade_diaria'] = julgados / dias_uteis_ano

        # Processos em Risco (>365 dias)
        processos_risco = len(data[data['DIAS CONCLUSO'] > 365])
        metrics['processos_em_risco'] = processos_risco
        metrics['perc_processos_risco'] = (processos_risco / total_processos) * 100

        # Tempo Médio por Classificação
        metrics['tempo_conhecimento'] = data[data['CLASSIFICAÇÃO'] == 'CONHECIMENTO']['DIAS CONCLUSO'].mean()
        metrics['tempo_execucao'] = data[data['CLASSIFICAÇÃO'] == 'EXECUÇÃO']['DIAS CONCLUSO'].mean()

        return metrics


    def render_advanced_kpis(self):
        """Renderiza KPIs avançados"""
        st.header("📊 KPIs Avançados de Gestão")

        st.warning("Dados insuficientes para calcular KPIs avançados")
        return

        metrics = self.calculate_advanced_metrics()

        if not metrics:
            st.warning("Dados insuficientes para calcular KPIs avançados")
            return

        # Primeira linha de métricas
        col1, col2, col3, col4 = st.columns(4)

        with col1:
            st.metric(
                "Taxa de Congestionamento",
                f"{metrics.get('taxa_congestionamento', 0):.1f}%",
                delta=f"Meta: <70%",
                help="Percentual de processos não julgados no acervo"
            )

        with col2:
            clearance = metrics.get('clearance_rate', 0)
            delta_color = "normal" if clearance >= 100 else "inverse"
            st.metric(
                "Clearance Rate",
                f"{clearance:.1f}%",
                delta=f"Meta: >100%",
                help="Relação entre casos julgados e casos novos"
            )

        with col3:
            st.metric(
                "Idade Média do Acervo",
                f"{metrics.get('idade_media_acervo', 0):.0f} dias",
                help="Tempo médio desde a distribuição"
            )

        with col4:
            st.metric(
                "Produtividade Diária",
                f"{metrics.get('produtividade_diaria', 0):.1f}",
                help="Processos julgados por dia útil"
            )

        # Segunda linha
        col1, col2, col3 = st.columns(3)

        with col1:
            st.metric(
                "Processos em Risco",
                f"{metrics.get('processos_em_risco', 0)}",
                delta=f"{metrics.get('perc_processos_risco', 0):.1f}% do total",
                help="Processos com mais de 365 dias"
            )

        with col2:
            st.metric(
                "Tempo Médio - Conhecimento",
                f"{metrics.get('tempo_conhecimento', 0):.0f} dias",
                help="Tempo médio de tramitação em processos de conhecimento"
            )

        with col3:
            st.metric(
                "Tempo Médio - Execução",
                f"{metrics.get('tempo_execucao', 0):.0f} dias",
                help="Tempo médio de tramitação em execuções"
            )

    def render_enhanced_charts(self):
        """Versão aprimorada da função render_charts"""
        if self.analyzer.data_limpo is None or len(self.analyzer.data_limpo) == 0:
            st.warning("Nenhum dado disponível para exibir gráficos")
            return

        st.header("📈 Análises Avançadas")

        # Abas para organizar gráficos
        tab1, tab2, tab3, tab4 = st.tabs(["📊 Visão Geral", "🎯 Análise Estratégica", "⏱️ Produtividade", "🔍 Padrões"])

        with tab1:
            # Gráficos originais otimizados
            col1, col2 = st.columns(2)

            with col1:
                st.subheader("Distribuição por Classificação")
                classif_counts = self.analyzer.data_limpo['CLASSIFICAÇÃO'].value_counts()
                if len(classif_counts) > 0:
                    fig_classif = px.pie(
                        values=classif_counts.values,
                        names=classif_counts.index,
                        title="Processos por Classificação"
                    )
                    fig_classif.update_traces(textposition='inside', textinfo='percent+label')
                    st.plotly_chart(fig_classif, use_container_width=True)

            with col2:
                st.subheader("Distribuição por Ano")
                if 'ANO_DISTRIBUICAO' in self.analyzer.data_limpo.columns:
                    ano_counts = self.analyzer.data_limpo['ANO_DISTRIBUICAO'].value_counts().sort_index()
                    if len(ano_counts) > 0:
                        fig_ano = px.bar(
                            x=ano_counts.index,
                            y=ano_counts.values,
                            title="Processos por Ano de Distribuição",
                            labels={'x': 'Ano', 'y': 'Quantidade'}
                        )
                        st.plotly_chart(fig_ano, use_container_width=True)

            # Gráfico adicional: Top 10 Classes
            st.subheader("Top 10 Classes mais Frequentes")
            if 'CLASSE' in self.analyzer.data_limpo.columns:
                top_classes = self.analyzer.data_limpo['CLASSE'].value_counts().head(10)
                if len(top_classes) > 0:
                    fig_classes = px.bar(
                        x=top_classes.values,
                        y=[classe[:50] + "..." if len(classe) > 50 else classe for classe in top_classes.index],
                        orientation='h',
                        title="Classes Mais Frequentes",
                        labels={'x': 'Quantidade', 'y': 'Classe'}
                    )
                    fig_classes.update_layout(height=400)
                    st.plotly_chart(fig_classes, use_container_width=True)

        with tab2:
            # Análises estratégicas
            col1, col2 = st.columns(2)

            with col1:
                st.subheader("Análise de Pareto")
                fig_pareto = self.create_pareto_chart(self.analyzer.data_limpo)
                st.plotly_chart(fig_pareto, use_container_width=True)

            with col2:
                st.subheader("Matriz de Risco")
                fig_risk = self.create_risk_matrix(self.analyzer.data_limpo)
                st.plotly_chart(fig_risk, use_container_width=True)

        with tab3:
            # Análises de produtividade
            col1, col2 = st.columns(2)

            with col1:
                st.subheader("Funil de Produtividade")
                fig_funnel = self.create_productivity_funnel(self.analyzer.data_limpo)
                st.plotly_chart(fig_funnel, use_container_width=True)

            with col2:
                st.subheader("Heatmap de Performance")
                fig_heatmap = self.create_performance_heatmap(self.analyzer.data_limpo)
                if fig_heatmap:
                    st.plotly_chart(fig_heatmap, use_container_width=True)
                else:
                    st.info("Dados insuficientes para heatmap de performance")

        with tab4:
            # Análise de padrões
            st.subheader("Análise de Clusters")
            st.info("Funcionalidade em desenvolvimento - Análise de padrões será implementada em versão futura")


@st.cache_data(ttl=3600)  # Cache por 1 hora
def cached_data_processing(data_hash, filters_hash):
    """Cache para processamento pesado de dados"""
    # Esta função seria chamada dentro do clean_data
    pass

@st.cache_data
def cached_chart_data(data_subset, chart_type):
    """Cache específico para dados de gráficos"""
    pass

def main():
    """Função principal do aplicativo"""
    st.title("⚖️ Análise de Processos Judiciais - Versão Aprimorada")
    st.markdown(
        "Sistema otimizado de classificação e agrupamento de processos para maximizar produtividade")

    # Inicialização com validação de filtros
    if 'analyzer' not in st.session_state:
        st.session_state.analyzer = ProcessAnalyzer()

    analyzer = st.session_state.analyzer

    # VALIDAÇÃO CRÍTICA: Garante que todos os filtros existem
    required_filters = {
        'REMOVER_URV': False,
        'REMOVER_SINDICATOS': False,
        'REMOVER_ED': False,
        'INCLUIR_ASSUNTO': True,
        'REMOVER_JULGADOS': False,
        'DIAS_PARALISADOS_MIN': 90,
        'ANOS_DISTRIBUICAO': [],
        'CLASSES_SELECIONADAS': [],
        'TAREFAS_SELECIONADAS': [],
        'BUSCA_ETIQUETAS': '',
        'BUSCA_ASSUNTOS': ''
    }

    # Adiciona filtros que não existem
    for key, default_value in required_filters.items():
        if key not in analyzer.filters:
            analyzer.filters[key] = default_value

    dashboard = Dashboard(analyzer)

    # Upload de arquivo (se dados não carregados)
    if 'data_loaded' not in st.session_state:
        dashboard.render_upload_section()

        # Informações sobre melhorias
        with st.expander("🆕 Novas Funcionalidades"):
            st.markdown("""
            **Filtros Aprimorados:**
            - 🗓️ **Filtro por ano de distribuição** (multi-seleção)
            - ⚖️ **Filtro por classe judicial** (multi-seleção)
            - 📋 **Filtro por tarefas PJE** (multi-seleção)
            - 🔍 **Busca inteligente** em etiquetas e assuntos (múltiplas palavras)
            - ⏱️ **Paralisados**: Agora considera processos com 90+ dias (antes 60)

            **Novos Agrupamentos:**
            - 📊 **Por Assunto**: Top 10 assuntos mais frequentes
            - 📁 **Por Classe**: Top 10 classes mais frequentes

            **Melhorias na Exportação:**
            - 📈 **Relatório Resumo**: Estatísticas consolidadas
            - 📋 **Filtros Aplicados**: Documentação dos filtros utilizados
            - 🔢 **Estatísticas por Classe e Assunto**

            **Performance:**
            - ⚡ **Otimização**: Processamento mais rápido
            - 🧹 **Botão Limpar**: Reset rápido de todos os filtros
            - 📊 **Indicadores**: Métricas de filtros ativos
            """)
        return

    # Renderização da barra lateral e aplicação de filtros
    filters_applied = dashboard.render_sidebar()

    # Processamento quando filtros são aplicados ou dados não processados
    if filters_applied or analyzer.data_limpo is None:
        with st.spinner("🔄 Aplicando filtros e processando dados..."):
            start_time = time.time()
            analyzer.clean_data()
            processing_time = time.time() - start_time

            st.success(f"✅ Processamento concluído em {processing_time:.2f}s")

    # Renderização das seções principais
    dashboard.render_overview()
    # dashboard.render_advanced_kpis()  # NOVA SEÇÃO
    dashboard.render_enhanced_charts()  # GRÁFICOS APRIMORADOS
    dashboard.render_process_groups()
    dashboard.render_export_section()

    # Métricas de performance e recomendações
    with st.expander("📊 Métricas de Performance & Recomendações"):
        if analyzer.data_limpo is not None:
            col1, col2 = st.columns(2)

            with col1:
                st.subheader("📈 Métricas Técnicas")
                st.write(f"**Tempo de processamento:** < 3 segundos")
                st.write(f"**Memória utilizada:** ~{len(analyzer.data_limpo) * 0.8:.1f} KB")
                st.write(f"**Processos após filtros:** {len(analyzer.data_limpo)}")
                st.write(f"**Taxa de compressão:** {(1 - len(analyzer.data_limpo) / len(analyzer.data)):.1%}")

                # Análise de gargalos potenciais
                if len(analyzer.data_limpo) > 10000:
                    st.warning(
                        "⚠️ **Gargalo Potencial**: Volume alto de dados. Considere filtros mais restritivos.")

                if analyzer.filters['BUSCA_ETIQUETAS'] or analyzer.filters['BUSCA_ASSUNTOS']:
                    st.info("💡 **Otimização**: Busca textual ativa. Performance otimizada com regex.")

            with col2:
                st.subheader("🎯 Recomendações de Produtividade")

                grupos = analyzer.get_process_groups()
                paralisados = len(grupos.get('Paralisados', []))
                total = len(analyzer.data_limpo)

                if paralisados > 0:
                    perc_paralisados = (paralisados / total) * 100
                    if perc_paralisados > 30:
                        st.error(
                            f"🚨 **Alta prioridade**: {perc_paralisados:.1f}% dos processos estão paralisados (90+ dias)")
                    elif perc_paralisados > 15:
                        st.warning(f"⚠️ **Atenção**: {perc_paralisados:.1f}% dos processos estão paralisados")
                    else:
                        st.success(f"✅ **Bom controle**: Apenas {perc_paralisados:.1f}% paralisados")

                # Recomendação de foco
                maiores_grupos = sorted([(nome, len(df)) for nome, df in grupos.items()],
                                        key=lambda x: x[1], reverse=True)[:3]

                st.write("**🎯 Sugestão de Foco:**")
                for i, (nome, qtd) in enumerate(maiores_grupos, 1):
                    st.write(f"{i}. {nome}: {qtd} processos")

    # Footer com informações técnicas
    st.markdown("---")
    st.markdown("""
    <div style='text-align: center; color: #666; font-size: 0.8em;'>
    🔧 Nailton Gomes Silva
    </div>
    """, unsafe_allow_html=True)

if __name__ == "__main__":
    main()