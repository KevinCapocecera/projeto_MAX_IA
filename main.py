
from modulos.assistente import responder_pergunta
from modulos.plano_acao import exportar_plano_acao
from modulos.base_dados import (
    localizar_planilha,
    listar_abas_analise,
    carregar_aba,
    buscar_item,
    resumo_numerico,
)


def iniciar_sexta_feira():
    print("\nMax | ASSISTENTE DE PCP")

    try:
        arquivo = localizar_planilha()
        abas = listar_abas_analise(arquivo)
    except Exception as erro:
        print(f"Erro ao carregar a base: {erro}")
        return

    if not abas:
        print("Nenhuma aba de análise foi encontrada.")
        return

    while True:
        print("\nAbas de análise disponíveis:")

        for numero, aba in enumerate(abas, start=1):
            print(f"{numero} - {aba}")

        print("0 - Encerrar")

        escolha = input("\nEscolha uma aba: ").strip()

        if escolha == "0":
            print("Max: Até a próxima!")
            break

        if not escolha.isdigit():
            print("Digite o número de uma das opções.")
            continue

        indice = int(escolha) - 1

        if indice < 0 or indice >= len(abas):
            print("Opção inválida.")
            continue

        nome_aba = abas[indice]

        try:
            df = carregar_aba(arquivo, nome_aba)
        except Exception as erro:
            print(f"Erro ao ler a aba: {erro}")
            continue

        print(f"\nMax: Analisando {nome_aba}")
        print(f"Registros encontrados: {len(df)}")
        print("Colunas disponíveis:")
        print(", ".join(map(str, df.columns)))

        while True:
            print("\n1 - Mostrar os primeiros 20 registros")
            print("2 - Buscar produto ou código")
            print("3 - Resumo numérico")
            print("4 - Escolher outra aba")
            print("5 - Exportar plano de ação para Excel")
            print("0 - Encerrar")

            opcao = input("\nVocê: ").strip()

            if opcao == "1":
                print(df.head(20).to_string(index=False))

            elif opcao == "2":
                termo = input("Digite o código ou nome: ").strip()

                if not termo:
                    print("Digite um termo para pesquisar.")
                    continue

                encontrados = buscar_item(df, termo)

                if encontrados.empty:
                    print("Nenhum registro encontrado.")
                else:
                    print(encontrados.head(50).to_string(index=False))
                    print(f"Total encontrado: {len(encontrados)}")

            elif opcao == "3":
                resumo_numerico(df)

            elif opcao == "4":
                break
            
            elif opcao == "5":
                try:
                    exportar_plano_acao(df, meta_doh=45)
                except Exception as erro:
                    print(f"Erro ao gerar o plano de ação: {erro}")

            elif opcao == "0":
                print("Max: Até a próxima!")
                return

            else:
                print("Opção inválida.")


if __name__ == "__main__":
    iniciar_sexta_feira()
